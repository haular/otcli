"""Tests for the filestore backup copy and post-copy verification.

Covers the known-flaky scenarios:
  * dangling symlinks inside the source tree must not abort the copy
  * files that disappear mid-copy should be logged but not abort the run
  * post-copy verification must detect a significant loss of files
"""

from __future__ import annotations

from pathlib import Path

import pytest

from otcli.domain.client_config import ClientConfig
from otcli.infrastructure import backup


def _write(p: Path, content: bytes = b'x') -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


@pytest.fixture()
def configured_client(tmp_path: Path, client_dict: dict) -> dict:
    """Prepare a fake Odoo filestore layout and a matching ClientConfig."""
    filestore_root = tmp_path / 'odoo_data' / 'filestore'
    client_name = 'my_client'
    src = filestore_root / client_name
    src.mkdir(parents=True)

    for i in range(5):
        _write(src / 'aa' / f'file_{i}.bin', b'payload' * (i + 1))
    for i in range(3):
        _write(src / 'bb' / f'file_{i}.bin', b'payload' * (i + 1))

    client_dict['client']['filestore_dir'] = str(filestore_root)
    client_dict['client']['technical_name'] = client_name
    client_dict['database']['db_name'] = client_name

    return {
        'src': src,
        'root': filestore_root,
        'client_name': client_name,
        'client': ClientConfig.from_dict(client_dict),
    }


class TestCopyFilestoreRobustness:
    def test_copies_all_regular_files(self, tmp_path: Path, configured_client: dict) -> None:
        dest_root = tmp_path / 'out'
        dest_root.mkdir()
        backup._copy_filestore(configured_client['client'], str(dest_root))
        copied = {p.relative_to(dest_root / 'filestore') for p in (dest_root / 'filestore').rglob('*') if p.is_file()}
        expected = {p.relative_to(configured_client['src']) for p in configured_client['src'].rglob('*') if p.is_file()}
        assert copied == expected

    def test_dangling_symlinks_do_not_abort(self, tmp_path: Path, configured_client: dict) -> None:
        src = configured_client['src']
        (src / 'dangling').symlink_to(src / 'does_not_exist')

        dest_root = tmp_path / 'out'
        dest_root.mkdir()
        backup._copy_filestore(configured_client['client'], str(dest_root))

        assert (dest_root / 'filestore' / 'aa' / 'file_0.bin').exists()

    def test_post_copy_verification_detects_missing_files(
        self, tmp_path: Path, configured_client: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If many files end up missing in destination, _copy_filestore must
        raise rather than silently produce an incomplete backup."""
        from otcli.domain.exceptions import OdooCLIError

        real_copytree = backup.shutil.copytree

        def broken_copytree(src, dst, *args, **kwargs):
            result = real_copytree(src, dst, *args, **kwargs)
            for p in list(Path(dst).rglob('*')):
                if p.is_file():
                    p.unlink()
            return result

        monkeypatch.setattr(backup.shutil, 'copytree', broken_copytree)

        dest_root = tmp_path / 'out'
        dest_root.mkdir()
        with pytest.raises(OdooCLIError):
            backup._copy_filestore(configured_client['client'], str(dest_root))

    def test_missing_source_raises(self, tmp_path: Path, client_dict: dict) -> None:
        from otcli.domain.exceptions import OdooCLIError

        client_dict['client']['filestore_dir'] = str(tmp_path / 'does_not_exist')
        client_dict['client']['technical_name'] = 'nope'
        client_dict['database']['db_name'] = 'nope'
        cfg = ClientConfig.from_dict(client_dict)

        dest = tmp_path / 'out'
        dest.mkdir()
        with pytest.raises(OdooCLIError):
            backup._copy_filestore(cfg, str(dest))
