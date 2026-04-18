"""Tests for the Docker-path database + filestore restore.

Covers:
  * restore succeeds even when the target database does not exist (bug B)
  * restore uses ``dropdb --if-exists`` and ``psql -v ON_ERROR_STOP=1``
  * an invalid zip (missing dump.sql) is rejected before touching the DB
  * temp extraction directory is cleaned up on both success and failure
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from odoo_task_cli.domain.exceptions import OdooCLIError
from odoo_task_cli.infrastructure import odoo_client


def _make_valid_backup(path: Path, filestore_files: int = 2) -> Path:
    """Create a minimal but valid backup zip at ``path``."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("dump.sql", "SELECT 1;")
        for i in range(filestore_files):
            zf.writestr(f"filestore/aa/file_{i}.bin", f"payload-{i}")
        zf.writestr(
            "manifest.json",
            '{"filestore_file_count": %d, "has_dump": true, "created_at": "x"}'
            % filestore_files,
        )
    return path


@pytest.fixture()
def configured_target(
    tmp_path: Path, fresh_config
) -> dict:
    filestore_root = tmp_path / "target_odoo" / "filestore"
    filestore_root.mkdir(parents=True)
    fresh_config.update(
        {
            "db_container_name": "odoo-db",
            "db_name": "target_db",
            "filestore_dir": str(filestore_root),
        }
    )
    return {"filestore_root": filestore_root}


class TestRestoreFromContainer:
    def test_restore_when_db_does_not_exist(
        self, tmp_path: Path, configured_target: dict
    ) -> None:
        """dropdb must tolerate a missing DB without aborting the restore."""
        backup = _make_valid_backup(tmp_path / "backup.zip")

        executed: list[str] = []

        def fake_exec(container, cmd, check=True):
            executed.append(cmd)
            # Simulate dropdb failing because DB does not exist.
            if cmd.startswith("dropdb") and check:
                raise AssertionError(
                    "dropdb should be called with check=False / --if-exists"
                )
            return MagicMock(exit_code=0, output=b"")

        with patch.object(odoo_client, "_get_container", return_value=MagicMock()), \
             patch.object(odoo_client, "_copy_file_to_container"), \
             patch.object(odoo_client, "_exec_in_container", side_effect=fake_exec):
            odoo_client.restore_database_from_container(str(backup))

        # Must have invoked createdb and psql with ON_ERROR_STOP.
        assert any(c.startswith("createdb") for c in executed)
        assert any("ON_ERROR_STOP=1" in c for c in executed if "psql" in c)

    def test_invalid_zip_without_dump_rejected(
        self, tmp_path: Path, configured_target: dict
    ) -> None:
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("not_a_dump.txt", "nope")

        with patch.object(odoo_client, "_get_container") as gc, \
             patch.object(odoo_client, "_copy_file_to_container") as cp, \
             patch.object(odoo_client, "_exec_in_container") as ex:
            with pytest.raises(OdooCLIError):
                odoo_client.restore_database_from_container(str(bad))
            gc.assert_not_called()
            cp.assert_not_called()
            ex.assert_not_called()

    def test_temp_extraction_cleaned_up_on_failure(
        self, tmp_path: Path, configured_target: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backup = _make_valid_backup(tmp_path / "backup.zip")

        # Track all created temp dirs so we can assert cleanup.
        created: list[str] = []
        real_mkdtemp = odoo_client.tempfile.mkdtemp

        def tracking_mkdtemp(*args, **kwargs):
            d = real_mkdtemp(*args, **kwargs)
            created.append(d)
            return d

        monkeypatch.setattr(odoo_client.tempfile, "mkdtemp", tracking_mkdtemp)

        def fake_exec(container, cmd, check=True):
            if "psql" in cmd:
                raise OdooCLIError("simulated psql failure")
            return MagicMock(exit_code=0, output=b"")

        with patch.object(odoo_client, "_get_container", return_value=MagicMock()), \
             patch.object(odoo_client, "_copy_file_to_container"), \
             patch.object(odoo_client, "_exec_in_container", side_effect=fake_exec):
            with pytest.raises(OdooCLIError):
                odoo_client.restore_database_from_container(str(backup))

        assert created, "tempfile.mkdtemp was not used"
        for d in created:
            assert not os.path.exists(d), f"temp dir {d} leaked"

    def test_filestore_restored_under_db_name(
        self, tmp_path: Path, configured_target: dict
    ) -> None:
        backup = _make_valid_backup(tmp_path / "backup.zip", filestore_files=3)

        with patch.object(odoo_client, "_get_container", return_value=MagicMock()), \
             patch.object(odoo_client, "_copy_file_to_container"), \
             patch.object(odoo_client, "_exec_in_container",
                          return_value=MagicMock(exit_code=0, output=b"")):
            odoo_client.restore_database_from_container(str(backup))

        final = configured_target["filestore_root"] / "target_db"
        assert final.is_dir()
        files = [p for p in final.rglob("*") if p.is_file()]
        assert len(files) == 3
