"""HTTP-based operations against Odoo's /web/database endpoints.

This module is a thin wrapper around the ``curl`` binary that targets Odoo's
database-manager endpoints. It is used by the CURL-path of the restore flow
(see :mod:`otcli.services.restore`).
"""

from __future__ import annotations

import logging
import subprocess

import typer

from otcli.bootstrap import config
from otcli.domain.exceptions import OdooCLIError
from otcli.domain.shell import run

logger = logging.getLogger(__name__)


def check_connection() -> bool:
    """Return True if Odoo's HTTP endpoint at ``config.url`` is reachable."""
    url = config.url
    typer.echo(f'Checking connection to Odoo server at {url}...')
    result = run(
        ['curl', '-Is', url],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def restore_database(backup_file: str = 'upgraded.zip') -> None:
    """POST ``backup_file`` to ``/web/database/restore``."""
    db_name = config.db_name
    master_pwd = config.master_pwd
    url = config.url

    typer.echo(f'Executing POST request to restore the database:\n - Database name: {db_name}\n - URL: {url}')

    run(
        [
            'curl',
            '-X',
            'POST',
            '-F',
            f'master_pwd={master_pwd}',
            '-F',
            f'name={db_name}',
            '-F',
            'copy=false',
            '-F',
            'neutralize_database=false',
            '-F',
            f'backup_file=@{backup_file}',
            f'{url}/web/database/restore',
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    typer.echo(f'Database {db_name} restored successfully')


def drop_database() -> None:
    """POST to ``/web/database/drop`` to remove the configured database."""
    db_name = config.db_name
    master_pwd = config.master_pwd
    url = config.url

    typer.echo(f'Dropping database {db_name}...')
    run(
        [
            'curl',
            '-X',
            'POST',
            '-F',
            f'master_pwd={master_pwd}',
            '-F',
            f'name={db_name}',
            f'{url}/web/database/drop',
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    typer.echo(f'Database {db_name} dropped successfully')


def get_database_list() -> list[str]:
    """List the databases visible to the Odoo container via ``odoo-bin --list``.

    Note: This runs inside ``config.db_container_name`` but invokes
    ``/mnt/odoo/odoo-bin``, which assumes a specific container layout. This
    is a pre-existing caveat from the original implementation.
    """
    container_name = config.db_container_name
    try:
        command = [
            'docker',
            'exec',
            container_name,
            '/mnt/odoo/odoo-bin',
            '-c',
            '/etc/odoo/odooshell.conf',
            '--list',
        ]
        result = run(command)
        output = result.stdout.strip()
        if not output:
            return []
        lines = output.split('\n')
        if len(lines) > 1:
            return [line.strip() for line in lines[1:] if line.strip()]
        return []
    except Exception as err:
        raise OdooCLIError(f'Failed to get database list: {err}') from err


def check_odoo_container_connection() -> bool:
    """Return True if the Odoo container can reach its own database manager."""
    container_name = config.db_container_name
    try:
        command = [
            'docker',
            'exec',
            container_name,
            'curl',
            '-s',
            'http://localhost:8069/web/database/manager',
        ]
        result = run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except Exception as err:
        raise OdooCLIError(f'Failed to check Odoo container connection: {err}') from err
