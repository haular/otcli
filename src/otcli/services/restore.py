"""Orchestrates the interactive restore flow for Odoo backups."""

from __future__ import annotations

import logging

import typer

from otcli.cli import prompts
from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import OdooCLIError
from otcli.infrastructure.odoo_http import (
    check_connection,
    drop_database,
    get_database_list,
    restore_database,
)
from otcli.infrastructure.restore import restore_database_from_container
from otcli.paths import Settings

logger = logging.getLogger(__name__)


def _select_backup_file(settings: Settings) -> str | None:
    """Prompt the user to pick a ``.zip`` from the backups directory."""
    backup_dir = settings.backups_dir
    if not backup_dir.is_dir():
        typer.echo(f'No backups directory yet: {backup_dir}.')
        return None

    zip_paths = sorted(backup_dir.glob('*.zip'))
    if not zip_paths:
        typer.echo(f'No .zip backup files found in {backup_dir}.')
        return None

    name_to_path = {p.name: str(p) for p in zip_paths}
    selected = prompts.pick_one('Select a backup file to restore', list(name_to_path.keys()))
    if selected is None:
        return None
    return name_to_path[selected]


def _restore_via_curl(client: ClientConfig, backup_file: str) -> None:
    """Restore using Odoo's HTTP /web/database/restore endpoint."""
    if not check_connection(client):
        logger.error('Odoo server is not running. Please start the server and try again.')
        raise OdooCLIError('Odoo server is not running. Please start the server and try again.')

    db_list = get_database_list(client)
    odoo_db_name = client.database.db_name

    if odoo_db_name in db_list:
        if not prompts.confirm(
            f'Database {odoo_db_name} already exists. Drop and recreate it?',
            default=True,
        ):
            return
        drop_database(client)

    restore_database(client, backup_file)


def _prompt_restore_method() -> str:
    """Ask the user for the restoration method. Returns 'd' or 'c'."""
    answer = prompts.pick_one(
        'Select restoration method',
        ['Docker container (psql)', 'HTTP / curl'],
    )
    if answer is None:
        raise OdooCLIError('No restoration method selected.')
    return 'd' if answer.startswith('Docker') else 'c'


def restore_odoo_database(client: ClientConfig, settings: Settings) -> None:
    """Interactive entry point used by the ``restore`` CLI command."""
    selected_backup_file = _select_backup_file(settings)
    if selected_backup_file is None:
        return

    method = _prompt_restore_method()
    if method == 'd':
        restore_database_from_container(client, selected_backup_file)
    else:
        _restore_via_curl(client, selected_backup_file)


__all__ = ['restore_odoo_database']
