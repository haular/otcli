"""Tests for the filestore ownership/mode alignment after restore.

When the CLI runs as one user (often root inside a devcontainer) but the
Odoo filestore on the host is owned by a different UID/GID (e.g. 1000:1000),
the restored filestore must be chown'd to match the owner/mode of the base
filestore directory so that Odoo can read it.

We do not actually switch UIDs in these tests: we mock ``os.chown`` and
``os.stat`` to assert the function calls the right primitives.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from otcli.infrastructure import odoo_client


class TestAlignOwnership:
    def test_applies_uid_gid_recursively(self, tmp_path: Path) -> None:
        # Build a reference dir and a target tree.
        ref = tmp_path / 'filestore'
        ref.mkdir()
        target = tmp_path / 'filestore' / 'target_db'
        target.mkdir()
        (target / 'aa').mkdir()
        (target / 'aa' / 'f1.bin').write_bytes(b'x')
        (target / 'aa' / 'f2.bin').write_bytes(b'y')

        # Pretend the reference directory belongs to 1000:1000 with mode 0o750.
        reference_stat = os.stat_result((stat.S_IFDIR | 0o750, 0, 0, 0, 1000, 1000, 0, 0, 0, 0))

        chown_calls: list[tuple[str, int, int]] = []
        chmod_calls: list[tuple[str, int]] = []

        real_stat = os.stat

        def fake_stat(path, *args, **kwargs):
            if str(path) == str(ref):
                return reference_stat
            return real_stat(path, *args, **kwargs)

        with (
            patch('os.stat', side_effect=fake_stat),
            patch('os.chown', side_effect=lambda p, u, g: chown_calls.append((str(p), u, g))),
            patch('os.chmod', side_effect=lambda p, m: chmod_calls.append((str(p), m))),
        ):
            odoo_client._align_ownership(str(target), str(ref))

        chowned_paths = {p for p, _, _ in chown_calls}
        assert str(target) in chowned_paths
        assert str(target / 'aa') in chowned_paths
        assert str(target / 'aa' / 'f1.bin') in chowned_paths
        assert str(target / 'aa' / 'f2.bin') in chowned_paths

        # All chown calls must use the reference UID/GID.
        for _, uid, gid in chown_calls:
            assert (uid, gid) == (1000, 1000)

        # Directories get the dir mode; files get mode & 0o666 by default.
        dir_modes = {p: m for p, m in chmod_calls if Path(p).is_dir()}
        assert dir_modes[str(target)] == 0o750
        assert dir_modes[str(target / 'aa')] == 0o750

    def test_permission_error_is_warned_not_raised(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        ref = tmp_path / 'filestore'
        ref.mkdir()
        target = ref / 'target_db'
        target.mkdir()
        (target / 'f.bin').write_bytes(b'x')

        reference_stat = os.stat_result((stat.S_IFDIR | 0o750, 0, 0, 0, 1000, 1000, 0, 0, 0, 0))

        def chown_raises(*a, **kw):
            raise PermissionError('Operation not permitted')

        real_stat = os.stat

        def fake_stat(path, *args, **kwargs):
            if str(path) == str(ref):
                return reference_stat
            return real_stat(path, *args, **kwargs)

        with (
            caplog.at_level('WARNING'),
            patch('os.stat', side_effect=fake_stat),
            patch('os.chown', side_effect=chown_raises),
            patch('os.chmod'),
        ):
            # Must NOT raise.
            odoo_client._align_ownership(str(target), str(ref))

        assert any(
            'permission' in rec.message.lower() or 'permiso' in rec.message.lower() for rec in caplog.records
        ), 'expected a WARNING about permissions'

    def test_missing_reference_is_warned_and_noop(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        ref = tmp_path / 'does_not_exist'
        target = tmp_path / 'target'
        target.mkdir()
        (target / 'f.bin').write_bytes(b'x')

        with caplog.at_level('WARNING'):
            # Must not raise and not touch anything.
            odoo_client._align_ownership(str(target), str(ref))

        # File is intact.
        assert (target / 'f.bin').exists()


class TestRestoreAlignsOwnership:
    def test_restore_invokes_align_ownership(self, tmp_path: Path, fresh_config) -> None:
        """After a successful Docker restore, the final filestore path is
        passed through _align_ownership along with config.filestore_dir."""
        import zipfile
        from unittest.mock import MagicMock

        backup = tmp_path / 'backup.zip'
        with zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('dump.sql', 'SELECT 1;')
            zf.writestr('filestore/aa/f1.bin', 'data')
            zf.writestr(
                'manifest.json',
                '{"filestore_file_count": 1, "has_dump": true, "created_at": "x"}',
            )

        filestore_root = tmp_path / 'target_odoo' / 'filestore'
        filestore_root.mkdir(parents=True)
        fresh_config.update(
            {
                'db_container_name': 'odoo-db',
                'db_name': 'target_db',
                'filestore_dir': str(filestore_root),
            }
        )

        align_calls: list[tuple[str, str]] = []

        def fake_align(path, reference):
            align_calls.append((path, reference))

        with (
            patch.object(odoo_client, '_get_container', return_value=MagicMock()),
            patch.object(odoo_client, '_copy_file_to_container'),
            patch.object(
                odoo_client,
                '_exec_in_container',
                return_value=MagicMock(exit_code=0, output=b''),
            ),
            patch.object(odoo_client, '_align_ownership', side_effect=fake_align),
        ):
            odoo_client.restore_database_from_container(str(backup))

        assert align_calls, 'restore did not call _align_ownership'
        path, reference = align_calls[0]
        assert path == str(filestore_root / 'target_db')
        assert reference == str(filestore_root)
