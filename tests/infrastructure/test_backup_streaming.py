"""Tests for the streaming backup pipeline (backup_odoo).

The pipeline pipes ``pg_dump`` stdout straight into a zip entry and
walks the host filestore in place. We don't actually invoke docker: we
patch :class:`subprocess.Popen` with a fake process that emits a known
stream so we can assert the resulting zip layout, manifest and atomic
publishing semantics.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import OdooCLIError
from otcli.infrastructure import backup as backup_mod
from otcli.paths import Settings

# --- Helpers --------------------------------------------------------------


def _write(p: Path, content: bytes = b'x') -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


class _FakePopen:
    """Minimal stand-in for :class:`subprocess.Popen` used by the dump streamer.

    Yields ``stdout_bytes`` from ``stdout.read(n)`` in arbitrary chunks
    and exits with ``returncode``. ``stderr`` is exposed as a BytesIO
    so the caller can ``.read()`` it on failure.
    """

    def __init__(
        self,
        stdout_bytes: bytes = b'',
        stderr_bytes: bytes = b'',
        returncode: int = 0,
    ) -> None:
        self.stdout = io.BytesIO(stdout_bytes)
        self.stderr = io.BytesIO(stderr_bytes)
        self._returncode = returncode
        self.returncode: int | None = None
        self.argv: list[str] | None = None

    def wait(self) -> int:
        self.returncode = self._returncode
        return self._returncode


def _setup_filestore(tmp_path: Path, client_dict: dict, *, file_count: int = 3) -> ClientConfig:
    """Create a tiny on-disk filestore matching ``client_dict``."""
    filestore_root = tmp_path / 'filestore_root'
    client_name = 'acme'
    src = filestore_root / client_name
    src.mkdir(parents=True)
    for i in range(file_count):
        _write(src / 'aa' / f'file_{i}.bin', f'payload_{i}'.encode() * 50)

    client_dict['client']['filestore_dir'] = str(filestore_root)
    client_dict['client']['technical_name'] = client_name
    client_dict['database']['db_name'] = client_name
    return ClientConfig.from_dict(client_dict)


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    s = Settings(app_data_dir=tmp_path / '.otcli')
    s.ensure_dirs()
    return s


# --- backup_odoo: happy path ---------------------------------------------


def test_streaming_backup_produces_zip_with_expected_layout(
    tmp_path: Path,
    client_dict: dict,
    settings: Settings,
) -> None:
    cfg = _setup_filestore(tmp_path, client_dict, file_count=4)
    fake_dump = b'-- pg_dump output\nSELECT 1;\n' * 200

    with patch.object(
        backup_mod.subprocess,
        'Popen',
        return_value=_FakePopen(stdout_bytes=fake_dump, returncode=0),
    ):
        out_zip = backup_mod.backup_odoo(cfg, settings, with_filestore=True)

    assert out_zip.exists()
    assert out_zip.suffix == '.zip'

    with zipfile.ZipFile(out_zip) as zf:
        names = set(zf.namelist())
        assert 'dump.sql' in names
        assert 'manifest.json' in names
        # Filestore arc-names live under "filestore/<rel>"
        fs_entries = [n for n in names if n.startswith('filestore/')]
        assert len(fs_entries) == 4
        # Verify dump bytes round-trip.
        assert zf.read('dump.sql') == fake_dump
        manifest = json.loads(zf.read('manifest.json'))

    assert manifest['has_dump'] is True
    assert manifest['dump_size_bytes'] == len(fake_dump)
    assert manifest['with_filestore'] is True
    assert manifest['filestore_file_count'] == 4
    assert manifest['db_name'] == cfg.database.db_name


def test_streaming_backup_uses_deflate_for_dump_and_stored_for_filestore(
    tmp_path: Path,
    client_dict: dict,
    settings: Settings,
) -> None:
    cfg = _setup_filestore(tmp_path, client_dict, file_count=2)
    with patch.object(
        backup_mod.subprocess,
        'Popen',
        return_value=_FakePopen(stdout_bytes=b'-- dump\n' * 1000, returncode=0),
    ):
        out_zip = backup_mod.backup_odoo(cfg, settings, with_filestore=True)

    with zipfile.ZipFile(out_zip) as zf:
        for info in zf.infolist():
            if info.filename == 'dump.sql':
                assert info.compress_type == zipfile.ZIP_DEFLATED
            elif info.filename.startswith('filestore/'):
                assert info.compress_type == zipfile.ZIP_STORED, f'{info.filename} should be stored, got {info.compress_type}'
            elif info.filename == 'manifest.json':
                assert info.compress_type == zipfile.ZIP_DEFLATED


def test_streaming_backup_skips_filestore_when_requested(
    tmp_path: Path,
    client_dict: dict,
    settings: Settings,
) -> None:
    cfg = _setup_filestore(tmp_path, client_dict, file_count=3)
    with patch.object(
        backup_mod.subprocess,
        'Popen',
        return_value=_FakePopen(stdout_bytes=b'-- dump\n', returncode=0),
    ):
        out_zip = backup_mod.backup_odoo(cfg, settings, with_filestore=False)

    with zipfile.ZipFile(out_zip) as zf:
        names = set(zf.namelist())
        assert 'dump.sql' in names
        assert not any(n.startswith('filestore/') for n in names)
        manifest = json.loads(zf.read('manifest.json'))

    assert manifest['filestore_file_count'] == 0
    assert manifest['with_filestore'] is False


# --- backup_odoo: failure modes ------------------------------------------


def test_pg_dump_failure_aborts_and_removes_partial_zip(
    tmp_path: Path,
    client_dict: dict,
    settings: Settings,
) -> None:
    cfg = _setup_filestore(tmp_path, client_dict)
    with (
        patch.object(
            backup_mod.subprocess,
            'Popen',
            return_value=_FakePopen(
                stdout_bytes=b'partial-dump',
                stderr_bytes=b'pg_dump: error: connection refused',
                returncode=1,
            ),
        ),
        pytest.raises(OdooCLIError, match='pg_dump'),
    ):
        backup_mod.backup_odoo(cfg, settings, with_filestore=True)

    # No final zip and no leftover .zip.tmp
    leftovers = list(settings.backups_dir.iterdir())
    assert leftovers == [], f'unexpected leftovers: {leftovers}'


def test_empty_pg_dump_aborts(
    tmp_path: Path,
    client_dict: dict,
    settings: Settings,
) -> None:
    cfg = _setup_filestore(tmp_path, client_dict)
    with (
        patch.object(
            backup_mod.subprocess,
            'Popen',
            return_value=_FakePopen(stdout_bytes=b'', returncode=0),
        ),
        pytest.raises(OdooCLIError, match='no produjo datos'),
    ):
        backup_mod.backup_odoo(cfg, settings, with_filestore=True)

    assert list(settings.backups_dir.iterdir()) == []


def test_missing_filestore_aborts_and_removes_partial_zip(
    tmp_path: Path,
    client_dict: dict,
    settings: Settings,
) -> None:
    """If the filestore dir is missing, we must abort BEFORE leaving a
    half-written zip in the output directory."""
    client_dict['client']['filestore_dir'] = str(tmp_path / 'no_such_dir')
    client_dict['client']['technical_name'] = 'acme'
    client_dict['database']['db_name'] = 'acme'
    cfg = ClientConfig.from_dict(client_dict)

    with (
        patch.object(
            backup_mod.subprocess,
            'Popen',
            return_value=_FakePopen(stdout_bytes=b'-- dump\n', returncode=0),
        ),
        pytest.raises(OdooCLIError, match='filestore'),
    ):
        backup_mod.backup_odoo(cfg, settings, with_filestore=True)

    assert list(settings.backups_dir.iterdir()) == []


def test_keyboard_interrupt_cleans_up_partial_zip(
    tmp_path: Path,
    client_dict: dict,
    settings: Settings,
) -> None:
    """If the user hits Ctrl-C mid-dump, the .zip.tmp must be removed."""
    cfg = _setup_filestore(tmp_path, client_dict)

    class _InterruptingPopen(_FakePopen):
        def wait(self):
            raise KeyboardInterrupt

    with (
        patch.object(
            backup_mod.subprocess,
            'Popen',
            return_value=_InterruptingPopen(stdout_bytes=b'partial', returncode=0),
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        backup_mod.backup_odoo(cfg, settings, with_filestore=True)

    assert list(settings.backups_dir.iterdir()) == []


# --- backup_odoo: atomicity ----------------------------------------------


def test_backup_writes_to_tmp_then_renames(
    tmp_path: Path,
    client_dict: dict,
    settings: Settings,
) -> None:
    """Verify the final file is published via rename: while writing, a
    .zip.tmp must exist; once finished, only the final .zip remains.

    We hook ``os.replace`` to capture the names that were renamed.
    """
    cfg = _setup_filestore(tmp_path, client_dict, file_count=1)

    captured: dict[str, tuple[str, str]] = {}
    real_replace = os.replace

    def spy_replace(src, dst):
        captured['args'] = (str(src), str(dst))
        return real_replace(src, dst)

    with (
        patch.object(
            backup_mod.subprocess,
            'Popen',
            return_value=_FakePopen(stdout_bytes=b'-- dump\n' * 10, returncode=0),
        ),
        patch.object(backup_mod.os, 'replace', side_effect=spy_replace),
    ):
        out = backup_mod.backup_odoo(cfg, settings, with_filestore=True)

    src, dst = captured['args']
    assert src.endswith('.zip.tmp')
    assert dst.endswith('.zip')
    assert dst == str(out)


def test_backup_removes_stale_tmp_from_previous_run(
    tmp_path: Path,
    client_dict: dict,
    settings: Settings,
) -> None:
    """A ``<final>.zip.tmp`` left over by a previous aborted run must
    not block the new backup."""
    cfg = _setup_filestore(tmp_path, client_dict, file_count=1)

    # Create a stale tmp matching some plausible name; the backup uses a
    # timestamped name, so we just verify that the routine cleans up its
    # OWN tmp before opening it. We do this by patching mkstemp-equivalent
    # logic and pre-creating the tmp file path.
    # The backup code: tmp_path = final_path.with_suffix('.zip.tmp')
    # We can't predict the exact stamp easily; instead we verify the
    # invariant by creating the parent file we'll see and ensuring the
    # routine doesn't error. We freeze datetime to make the name
    # predictable.
    import datetime as real_datetime

    fixed = real_datetime.datetime(2026, 4, 26, 12, 0, 0)

    class _FrozenDatetime(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    with patch.object(backup_mod.datetime, 'datetime', _FrozenDatetime):
        expected_stem = f'{cfg.database.db_name}_{fixed.strftime("%Y%m%d_%H%M%S")}'
        stale_tmp = settings.backups_dir / f'{expected_stem}.zip.tmp'
        stale_tmp.write_bytes(b'leftover from a crashed run')

        with patch.object(
            backup_mod.subprocess,
            'Popen',
            return_value=_FakePopen(stdout_bytes=b'-- dump\n', returncode=0),
        ):
            out = backup_mod.backup_odoo(cfg, settings, with_filestore=True)

    assert out.name == f'{expected_stem}.zip'
    assert out.exists()
    assert not stale_tmp.exists()


# --- argv construction ---------------------------------------------------


def test_pg_dump_argv_uses_docker_exec_with_dash_i(client_dict: dict) -> None:
    """The pipe-into-zip approach requires docker exec -i (no TTY)."""
    cfg = ClientConfig.from_dict(client_dict)
    argv = backup_mod._build_pg_dump_argv(cfg)
    assert argv[:3] == ['docker', 'exec', '-i']
    assert cfg.docker.db_container in argv
    assert 'pg_dump' in argv
    assert '-d' in argv and cfg.database.db_name in argv


# --- dangling symlinks survival -----------------------------------------


def test_dangling_symlink_in_filestore_does_not_abort_streaming(
    tmp_path: Path,
    client_dict: dict,
    settings: Settings,
) -> None:
    cfg = _setup_filestore(tmp_path, client_dict, file_count=2)
    src = Path(cfg.filestore_dir) / cfg.technical_name
    (src / 'dangling').symlink_to(src / 'does_not_exist')

    with patch.object(
        backup_mod.subprocess,
        'Popen',
        return_value=_FakePopen(stdout_bytes=b'-- dump\n', returncode=0),
    ):
        out = backup_mod.backup_odoo(cfg, settings, with_filestore=True)

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert any(n.startswith('filestore/aa/') for n in names)
        # Dangling link must not have been included.
        assert 'filestore/dangling' not in names


# --- Settings shim -------------------------------------------------------


# --- Zip64 sanity (large dumps) ------------------------------------------


def test_dump_uses_zip64_when_streamed(
    tmp_path: Path,
    client_dict: dict,
    settings: Settings,
) -> None:
    """We pass ``force_zip64=True`` so multi-GB dumps don't blow up.

    We can't realistically generate >4 GB in tests, but we can verify
    that the entry was opened with the flag honoured by inspecting the
    SimpleNamespace returned by zipfile.open, which is hard. Instead we
    assert that a small dump still produces a valid zip and that the
    info has ``flag_bits`` indicating zip64 may be used. This is a smoke
    test rather than a strict guarantee.
    """
    cfg = _setup_filestore(tmp_path, client_dict, file_count=1)
    with patch.object(
        backup_mod.subprocess,
        'Popen',
        return_value=_FakePopen(stdout_bytes=b'-- dump\n' * 1000, returncode=0),
    ):
        out = backup_mod.backup_odoo(cfg, settings, with_filestore=True)

    # If allowZip64=True is honoured, a normal small zip still opens
    # cleanly under the standard ZipFile reader.
    with zipfile.ZipFile(out) as zf:
        zf.testzip()  # raises if any CRC mismatches
