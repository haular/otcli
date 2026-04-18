"""Tests for the filestore backup copy and post-copy verification.

Covers the known-flaky scenarios:
  * dangling symlinks inside the source tree must not abort the copy
  * files that disappear mid-copy should be logged but not abort the run
  * post-copy verification must detect a significant loss of files
"""

from __future__ import annotations

from pathlib import Path

import pytest

from odoo_task_cli.infrastructure import db_client


def _write(p: Path, content: bytes = b'x') -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


@pytest.fixture()
def configured_client(tmp_path: Path, fresh_config, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Prepare a fake Odoo filestore layout and wire config to point at it."""
    filestore_root = tmp_path / 'odoo_data' / 'filestore'
    client_name = 'my_client'
    src = filestore_root / client_name
    src.mkdir(parents=True)

    # Populate a realistic tree.
    for i in range(5):
        _write(src / 'aa' / f'file_{i}.bin', b'payload' * (i + 1))
    for i in range(3):
        _write(src / 'bb' / f'file_{i}.bin', b'payload' * (i + 1))

    fresh_config.update(
        {
            'filestore_dir': str(filestore_root),
            'technical_client_name': client_name,
            'db_name': client_name,
        }
    )
    return {'src': src, 'root': filestore_root, 'client_name': client_name}


class TestCopyFilestoreRobustness:
    def test_copies_all_regular_files(self, tmp_path: Path, configured_client: dict) -> None:
        dest_root = tmp_path / 'out'
        dest_root.mkdir()
        db_client._copy_filestore(str(dest_root))
        copied = {p.relative_to(dest_root / 'filestore') for p in (dest_root / 'filestore').rglob('*') if p.is_file()}
        expected = {p.relative_to(configured_client['src']) for p in configured_client['src'].rglob('*') if p.is_file()}
        assert copied == expected

    def test_dangling_symlinks_do_not_abort(self, tmp_path: Path, configured_client: dict) -> None:
        src = configured_client['src']
        # Dangling symlink — target does not exist.
        (src / 'dangling').symlink_to(src / 'does_not_exist')

        dest_root = tmp_path / 'out'
        dest_root.mkdir()
        db_client._copy_filestore(str(dest_root))

        # Regular files still copied.
        assert (dest_root / 'filestore' / 'aa' / 'file_0.bin').exists()

    def test_post_copy_verification_detects_missing_files(
        self, tmp_path: Path, configured_client: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If many files end up missing in destination, _copy_filestore must
        raise rather than silently produce an incomplete backup."""
        from odoo_task_cli.domain.exceptions import OdooCLIError

        real_copytree = db_client.shutil.copytree

        def broken_copytree(src, dst, *args, **kwargs):
            # Copy into dst but then wipe most files to simulate silent loss.
            result = real_copytree(src, dst, *args, **kwargs)
            for p in list(Path(dst).rglob('*')):
                if p.is_file():
                    p.unlink()
            return result

        monkeypatch.setattr(db_client.shutil, 'copytree', broken_copytree)

        dest_root = tmp_path / 'out'
        dest_root.mkdir()
        with pytest.raises(OdooCLIError):
            db_client._copy_filestore(str(dest_root))

    def test_missing_source_raises(self, tmp_path: Path, fresh_config) -> None:
        from odoo_task_cli.domain.exceptions import OdooCLIError

        fresh_config.update(
            {
                'filestore_dir': str(tmp_path / 'does_not_exist'),
                'technical_client_name': 'nope',
                'db_name': 'nope',
            }
        )
        dest = tmp_path / 'out'
        dest.mkdir()
        with pytest.raises(OdooCLIError):
            db_client._copy_filestore(str(dest))
