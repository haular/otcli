"""Upgrade service: orchestrates ``infrastructure.upgrade.run_upgrade``."""

from __future__ import annotations

import logging
import os

import typer

from otcli.infrastructure.upgrade import check_existing_upgrade, run_upgrade

logger = logging.getLogger(__name__)


def upgrade_database(backup_file: str) -> str:
    """Upgrade ``backup_file`` via the upstream Odoo upgrade service.

    If a previously-produced ``upgraded.zip`` is present next to the
    input backup, the user is asked whether to reuse it. The returned
    string is always the absolute path to the upgraded archive on disk.
    """
    if check_existing_upgrade(backup_file) and typer.confirm('Upgraded file found. Do you want to reuse it?', default=True):
        directory = os.path.dirname(os.path.abspath(backup_file))
        existing = os.path.join(directory, 'upgraded.zip')
        typer.echo(f'Reusing existing upgraded file: {existing}')
        return existing
    return run_upgrade(backup_file)
