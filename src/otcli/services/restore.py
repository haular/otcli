"""Orchestrates the interactive restore flow for Odoo backups."""

from __future__ import annotations

import glob
import logging
import os

import typer

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
    backup_dir = str(settings.backups_dir)
    zip_files = sorted(glob.glob(os.path.join(backup_dir, '*.zip')))

    if not zip_files:
        typer.echo(f'No .zip backup files found in {backup_dir}.')
        return None

    typer.echo(f'Found {len(zip_files)} backup files in {backup_dir}:')
    for i, zip_file in enumerate(zip_files, 1):
        typer.echo(f'  {i}: {os.path.basename(zip_file)}')

    while True:
        try:
            choice = typer.prompt('Select a backup file to restore (enter number)', type=int)
        except ValueError:
            typer.echo('Invalid input. Please enter a number.')
            continue
        index = choice - 1
        if 0 <= index < len(zip_files):
            return zip_files[index]
        typer.echo('Invalid selection. Please enter a valid number.')


def _restore_via_curl(client: ClientConfig, backup_file: str) -> None:
    """Restore using Odoo's HTTP /web/database/restore endpoint."""
    if not check_connection(client):
        logger.error('Odoo server is not running. Please start the server and try again.')
        raise OdooCLIError('Odoo server is not running. Please start the server and try again.')

    db_list = get_database_list(client)
    odoo_db_name = client.database.db_name

    if odoo_db_name in db_list:
        if not typer.confirm(
            f'Database {odoo_db_name} already exists. Do you want to drop and recreate it?',
            default=True,
        ):
            return
        drop_database(client)

    restore_database(client, backup_file)


def _prompt_restore_method() -> str:
    """Ask the user for the restoration method. Returns 'd' or 'c'."""
    while True:
        choice = typer.prompt(
            'Select restoration method: (C)URL or (D)ocker container? [C/D] (Default: D)',
            default='D',
        ).lower()
        if choice in ('', 'd'):
            return 'd'
        if choice == 'c':
            return 'c'
        typer.echo("Invalid restoration method. Please choose 'C' for CURL or 'D' for Docker container.")


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
