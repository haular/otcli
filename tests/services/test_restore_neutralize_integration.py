"""Integration tests for the auto-neutralize hook in services/restore.py."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import NeutralizeError
from otcli.paths import Settings
from otcli.services import restore as restore_service


def _put_zip(path: Path) -> None:
    # Minimal zip; the actual restore is mocked.
    path.write_bytes(b'PK\x05\x06' + b'\x00' * 18)


@pytest.fixture()
def settings_with_backup(tmp_path: Path) -> tuple[Settings, str]:
    settings = Settings(app_data_dir=tmp_path / '.otcli_config')
    settings.ensure_dirs()
    backup = settings.backups_dir / 'acme.zip'
    _put_zip(backup)
    return settings, str(backup)


def test_test_environment_invokes_neutralize(client_dict: dict, settings_with_backup) -> None:
    settings, backup_path = settings_with_backup
    client_dict['upgrade']['environment'] = 'test'
    client = ClientConfig.from_dict(client_dict)

    with (
        patch.object(restore_service, 'restore_database_from_container') as mock_restore,
        patch.object(restore_service, 'neutralize_database') as mock_neutralize,
        patch.object(restore_service.prompts, 'pick_one', return_value='acme.zip'),
    ):
        restore_service.restore_odoo_database(client, settings)

    mock_restore.assert_called_once_with(client, backup_path)
    mock_neutralize.assert_called_once_with(client)


def test_production_environment_skips_neutralize(client_dict: dict, settings_with_backup) -> None:
    settings, _ = settings_with_backup
    client_dict['upgrade']['environment'] = 'production'
    client = ClientConfig.from_dict(client_dict)

    with (
        patch.object(restore_service, 'restore_database_from_container'),
        patch.object(restore_service, 'neutralize_database') as mock_neutralize,
        patch.object(restore_service.prompts, 'pick_one', return_value='acme.zip'),
    ):
        restore_service.restore_odoo_database(client, settings)

    mock_neutralize.assert_not_called()


def test_neutralize_failure_does_not_propagate(
    client_dict: dict,
    settings_with_backup,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Neutralize errors are logged at WARNING but the restore returns normally."""
    settings, _ = settings_with_backup
    client_dict['upgrade']['environment'] = 'test'
    client = ClientConfig.from_dict(client_dict)

    with (
        patch.object(restore_service, 'restore_database_from_container'),
        patch.object(
            restore_service,
            'neutralize_database',
            side_effect=NeutralizeError('odoo-bin not found'),
        ),
        patch.object(restore_service.prompts, 'pick_one', return_value='acme.zip'),
        caplog.at_level(logging.WARNING),
    ):
        # Must not raise.
        restore_service.restore_odoo_database(client, settings)

    assert any('Neutralize failed' in r.message for r in caplog.records)


def test_no_backup_selected_skips_everything(client_dict: dict, settings_with_backup) -> None:
    settings, _ = settings_with_backup
    client = ClientConfig.from_dict(client_dict)

    with (
        patch.object(restore_service, 'restore_database_from_container') as mock_restore,
        patch.object(restore_service, 'neutralize_database') as mock_neutralize,
        patch.object(restore_service.prompts, 'pick_one', return_value=None),
    ):
        restore_service.restore_odoo_database(client, settings)

    mock_restore.assert_not_called()
    mock_neutralize.assert_not_called()
