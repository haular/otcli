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

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import OdooCLIError
from otcli.infrastructure import restore as restore_mod


def _make_valid_backup(path: Path, filestore_files: int = 2) -> Path:
    """Create a minimal but valid backup zip at ``path``."""
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('dump.sql', 'SELECT 1;')
        for i in range(filestore_files):
            zf.writestr(f'filestore/aa/file_{i}.bin', f'payload-{i}')
        zf.writestr(
            'manifest.json',
            f'{{"filestore_file_count": {filestore_files}, "has_dump": true, "created_at": "x"}}',
        )
    return path


@pytest.fixture()
def configured_target(tmp_path: Path, client_dict: dict) -> dict:
    filestore_root = tmp_path / 'target_odoo' / 'filestore'
    filestore_root.mkdir(parents=True)

    client_dict['client']['filestore_dir'] = str(filestore_root)
    client_dict['client']['technical_name'] = 'target_db'
    client_dict['database']['db_name'] = 'target_db'
    client_dict['docker']['db_container'] = 'odoo-db'

    return {
        'filestore_root': filestore_root,
        'client': ClientConfig.from_dict(client_dict),
    }


class TestRestoreFromContainer:
    def test_restore_when_db_does_not_exist(self, tmp_path: Path, configured_target: dict) -> None:
        """dropdb must tolerate a missing DB without aborting the restore."""
        backup = _make_valid_backup(tmp_path / 'backup.zip')

        executed: list[str] = []

        def fake_exec(container, cmd, check=True):
            executed.append(cmd)
            if cmd.startswith('dropdb') and check:
                raise AssertionError('dropdb should be called with check=False / --if-exists')
            return MagicMock(exit_code=0, output=b'')

        with (
            patch.object(restore_mod, '_get_container', return_value=MagicMock()),
            patch.object(restore_mod, '_copy_file_to_container'),
            patch.object(restore_mod, '_exec_in_container', side_effect=fake_exec),
        ):
            restore_mod.restore_database_from_container(configured_target['client'], str(backup))

        assert any(c.startswith('createdb') for c in executed)
        assert any('ON_ERROR_STOP=1' in c for c in executed if 'psql' in c)

    def test_invalid_zip_without_dump_rejected(self, tmp_path: Path, configured_target: dict) -> None:
        bad = tmp_path / 'bad.zip'
        with zipfile.ZipFile(bad, 'w') as zf:
            zf.writestr('not_a_dump.txt', 'nope')

        with (
            patch.object(restore_mod, '_get_container') as gc,
            patch.object(restore_mod, '_copy_file_to_container') as cp,
            patch.object(restore_mod, '_exec_in_container') as ex,
            pytest.raises(OdooCLIError),
        ):
            restore_mod.restore_database_from_container(configured_target['client'], str(bad))
        gc.assert_not_called()
        cp.assert_not_called()
        ex.assert_not_called()

    def test_temp_extraction_cleaned_up_on_failure(
        self, tmp_path: Path, configured_target: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backup = _make_valid_backup(tmp_path / 'backup.zip')

        created: list[str] = []
        real_mkdtemp = restore_mod.tempfile.mkdtemp

        def tracking_mkdtemp(*args, **kwargs):
            d = real_mkdtemp(*args, **kwargs)
            created.append(d)
            return d

        monkeypatch.setattr(restore_mod.tempfile, 'mkdtemp', tracking_mkdtemp)

        def fake_exec(container, cmd, check=True):
            if 'psql' in cmd:
                raise OdooCLIError('simulated psql failure')
            return MagicMock(exit_code=0, output=b'')

        with (
            patch.object(restore_mod, '_get_container', return_value=MagicMock()),
            patch.object(restore_mod, '_copy_file_to_container'),
            patch.object(restore_mod, '_exec_in_container', side_effect=fake_exec),
            pytest.raises(OdooCLIError),
        ):
            restore_mod.restore_database_from_container(configured_target['client'], str(backup))

        assert created, 'tempfile.mkdtemp was not used'
        for d in created:
            assert not os.path.exists(d), f'temp dir {d} leaked'

    def test_terminates_active_connections_before_dropdb(
        self, tmp_path: Path, configured_target: dict
    ) -> None:
        """Restore must run pg_terminate_backend BEFORE dropdb so that
        active Odoo workers don't keep the database busy and make
        ``dropdb`` silently fail."""
        backup = _make_valid_backup(tmp_path / 'backup.zip')

        executed: list[str] = []

        def fake_exec(container, cmd, check=True):
            executed.append(cmd)
            return MagicMock(exit_code=0, output=b'')

        with (
            patch.object(restore_mod, '_get_container', return_value=MagicMock()),
            patch.object(restore_mod, '_copy_file_to_container'),
            patch.object(restore_mod, '_exec_in_container', side_effect=fake_exec),
        ):
            restore_mod.restore_database_from_container(configured_target['client'], str(backup))

        # Find indices of the relevant commands and assert ordering.
        terminate_idx = next(
            (i for i, c in enumerate(executed) if 'pg_terminate_backend' in c),
            -1,
        )
        dropdb_idx = next((i for i, c in enumerate(executed) if c.startswith('dropdb')), -1)
        createdb_idx = next((i for i, c in enumerate(executed) if c.startswith('createdb')), -1)

        assert terminate_idx >= 0, 'pg_terminate_backend was not invoked'
        assert dropdb_idx >= 0, 'dropdb was not invoked'
        assert createdb_idx >= 0, 'createdb was not invoked'
        assert terminate_idx < dropdb_idx < createdb_idx, (
            f'wrong order: terminate={terminate_idx}, dropdb={dropdb_idx}, createdb={createdb_idx}'
        )

    def test_terminate_query_targets_correct_database(
        self, tmp_path: Path, configured_target: dict
    ) -> None:
        """The pg_terminate_backend SELECT must filter by the target db
        name AND exclude its own backend (pg_backend_pid)."""
        backup = _make_valid_backup(tmp_path / 'backup.zip')

        executed: list[str] = []

        def fake_exec(container, cmd, check=True):
            executed.append(cmd)
            return MagicMock(exit_code=0, output=b'')

        with (
            patch.object(restore_mod, '_get_container', return_value=MagicMock()),
            patch.object(restore_mod, '_copy_file_to_container'),
            patch.object(restore_mod, '_exec_in_container', side_effect=fake_exec),
        ):
            restore_mod.restore_database_from_container(configured_target['client'], str(backup))

        terminate_cmds = [c for c in executed if 'pg_terminate_backend' in c]
        assert terminate_cmds, 'no pg_terminate_backend command issued'
        cmd = terminate_cmds[0]
        assert "datname = 'target_db'" in cmd
        assert 'pg_backend_pid()' in cmd  # exclude self
        # Must run against `postgres`, not the (possibly missing) target db.
        assert '-d postgres' in cmd

    def test_aborts_clearly_when_dropdb_silently_failed(
        self, tmp_path: Path, configured_target: dict
    ) -> None:
        """If after dropdb the database still exists (e.g. new sessions
        reconnected), we must abort with a clear, actionable error
        instead of letting createdb fail with the obscure 'database
        already exists' message."""
        backup = _make_valid_backup(tmp_path / 'backup.zip')

        # Sequence of (cmd_match, exit_code, output) responses.
        # _database_exists -> output '1' -> True
        def fake_exec(container, cmd, check=True):
            if 'pg_database WHERE datname' in cmd:
                # database STILL exists after dropdb
                return MagicMock(exit_code=0, output=b'1\n')
            return MagicMock(exit_code=0, output=b'')

        with (
            patch.object(restore_mod, '_get_container', return_value=MagicMock()),
            patch.object(restore_mod, '_copy_file_to_container'),
            patch.object(restore_mod, '_exec_in_container', side_effect=fake_exec),
            pytest.raises(OdooCLIError, match='still exists after dropdb'),
        ):
            restore_mod.restore_database_from_container(configured_target['client'], str(backup))

    def test_terminate_failure_is_warned_but_does_not_abort(
        self, tmp_path: Path, configured_target: dict
    ) -> None:
        """If the terminate query itself fails (e.g. permission denied),
        we should log a warning and proceed: dropdb may still succeed
        on its own."""
        backup = _make_valid_backup(tmp_path / 'backup.zip')

        def fake_exec(container, cmd, check=True):
            if 'pg_terminate_backend' in cmd:
                return MagicMock(exit_code=1, output=b'permission denied')
            return MagicMock(exit_code=0, output=b'')

        with (
            patch.object(restore_mod, '_get_container', return_value=MagicMock()),
            patch.object(restore_mod, '_copy_file_to_container'),
            patch.object(restore_mod, '_exec_in_container', side_effect=fake_exec),
        ):
            # Must NOT raise.
            restore_mod.restore_database_from_container(configured_target['client'], str(backup))

    def test_filestore_restored_under_db_name(self, tmp_path: Path, configured_target: dict) -> None:
        backup = _make_valid_backup(tmp_path / 'backup.zip', filestore_files=3)

        with (
            patch.object(restore_mod, '_get_container', return_value=MagicMock()),
            patch.object(restore_mod, '_copy_file_to_container'),
            patch.object(restore_mod, '_exec_in_container', return_value=MagicMock(exit_code=0, output=b'')),
        ):
            restore_mod.restore_database_from_container(configured_target['client'], str(backup))

        final = configured_target['filestore_root'] / 'target_db'
        assert final.is_dir()
        files = [p for p in final.rglob('*') if p.is_file()]
        assert len(files) == 3
