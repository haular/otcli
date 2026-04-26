"""Odoo upgrade helpers wrapping the official ``upgrade.odoo.com`` script.

The upstream script downloads ``odoo-upgrade.py`` and runs it with the
backup file as an input. It writes ``upgraded.zip`` next to the current
working directory. We host that download inside a managed temporary
directory and return the absolute path to the produced archive so the
caller never has to depend on the process ``cwd``.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

import typer

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import OdooCLIError
from otcli.domain.shell import run

logger = logging.getLogger(__name__)

_UPSTREAM_UPGRADE_URL = 'https://upgrade.odoo.com/upgrade'


def _download_upgrade_script(target_dir: Path) -> Path:
    """Download the Odoo upgrade script into ``target_dir``.

    Returns the absolute path to the downloaded file.
    """
    script_path = target_dir / 'odoo-upgrade.py'
    typer.echo('Downloading Odoo upgrade script...')
    run(['curl', '-fsS', _UPSTREAM_UPGRADE_URL, '-o', str(script_path)])
    return script_path


def run_upgrade(client: ClientConfig, backup_file: str) -> str:
    """Run the upstream upgrade script against ``backup_file``.

    Returns the absolute path to the produced ``upgraded.zip`` archive.

    The script is downloaded into a temporary directory that is cleaned
    up automatically; ``upgraded.zip`` is moved next to the input
    ``backup_file`` so the caller can find it deterministically.
    """
    code_subscription = client.upgrade.code_subscription
    target_version = client.upgrade.target
    environment = client.upgrade.environment

    backup_path = Path(backup_file).resolve()
    if not backup_path.is_file():
        raise OdooCLIError(f'Backup file not found: {backup_path}')

    logger.info('Running Odoo upgrade service for %s...', backup_path)
    logger.info('Target version: %s', target_version)

    # Use a managed temporary directory: the upstream script writes
    # upgraded.zip next to the cwd, so we cd there transiently via the
    # subprocess invocation (run() inherits our cwd; we control it by
    # downloading and invoking the script inside ``td``).
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory(prefix='otcli_upgrade_') as td_str:
        td = Path(td_str)
        try:
            os.chdir(td)
            script_path = _download_upgrade_script(td)
            run(
                [
                    'python3',
                    str(script_path),
                    environment,
                    '-i',
                    str(backup_path),
                    '-c',
                    code_subscription,
                    '-t',
                    target_version,
                ]
            )
            produced = td / 'upgraded.zip'
            if not produced.is_file():
                raise OdooCLIError(
                    f'Upgrade finished but {produced} was not created. Check the upstream script output above.'
                )

            # Move the result next to the input backup so callers find
            # it at a deterministic, persistent location.
            destination = backup_path.parent / 'upgraded.zip'
            if destination.exists():
                destination.unlink()
            shutil.move(str(produced), destination)
        finally:
            # Always restore the caller's cwd, even if the upstream
            # script crashed or raised before completion.
            os.chdir(original_cwd)

    return str(destination)


def check_existing_upgrade(backup_file: str) -> bool:
    """Return True if an ``upgraded.zip`` already exists next to ``backup_file``."""
    directory = os.path.dirname(os.path.abspath(backup_file))
    return os.path.exists(os.path.join(directory, 'upgraded.zip'))
