"""Orchestrates the interactive restore flow for Odoo backups.

Restore now has a single path: extract the archive, recreate the target
database via the Postgres container, and move the filestore back into
place. The HTTP/database-manager path was removed because every
deployment we support already uses the Docker path.
"""

from __future__ import annotations

import logging

import typer

from otcli.cli import prompts
from otcli.domain.client_config import ClientConfig
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


def restore_odoo_database(client: ClientConfig, settings: Settings) -> None:
    """Interactive entry point used by the ``restore`` CLI command."""
    selected_backup_file = _select_backup_file(settings)
    if selected_backup_file is None:
        return

    restore_database_from_container(client, selected_backup_file)


__all__ = ['restore_odoo_database']
