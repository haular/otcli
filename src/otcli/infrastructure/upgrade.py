"""Odoo upgrade helpers wrapping the official upgrade.odoo.com script."""

from __future__ import annotations

import logging
import os

import typer

from otcli.bootstrap import config
from otcli.domain.shell import run

logger = logging.getLogger(__name__)


def download_upgrade_script() -> str:
    """Download the Odoo upgrade script into the current working directory.

    Returns the (relative) path to the downloaded file.
    """
    typer.echo('Downloading Odoo upgrade script...')
    run(['curl', 'https://upgrade.odoo.com/upgrade', '-o', 'odoo-upgrade.py'])
    return 'odoo-upgrade.py'


def run_upgrade(backup_file: str) -> str:
    """Run the upstream upgrade script against ``backup_file`` and return the
    path to the produced ``upgraded.zip``.
    """
    code_subscription = config.code_subscription
    target_version = config.upgrade_target
    environment = config.environment

    logger.info('Running Odoo upgrade service for %s...', backup_file)
    logger.info('Target version: %s', config.upgrade_target)

    upgrade_script = download_upgrade_script()
    try:
        run(
            [
                'python3',
                upgrade_script,
                environment,
                '-i',
                backup_file,
                '-c',
                code_subscription,
                '-t',
                target_version,
            ]
        )
    finally:
        if os.path.exists(upgrade_script):
            os.remove(upgrade_script)

    return 'upgraded.zip'


def check_existing_upgrade(backup_file: str) -> bool:
    """Return True if an ``upgraded.zip`` already exists next to ``backup_file``."""
    directory = os.path.dirname(os.path.abspath(backup_file))
    return os.path.exists(os.path.join(directory, 'upgraded.zip'))
