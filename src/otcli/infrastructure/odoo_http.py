"""HTTP-based operations against Odoo's /web/database endpoints.

This module is a thin wrapper around the ``curl`` binary that targets Odoo's
database-manager endpoints. It is used by the CURL-path of the restore flow
(see :mod:`otcli.services.restore`).

All public operations that perform a POST check the returned HTTP status
code and raise :class:`OdooCLIError` on anything >= 400 so that errors like
a wrong master password or a 500 from Odoo cannot be mistaken for success.
"""

from __future__ import annotations

import logging
import subprocess

import typer

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import OdooCLIError
from otcli.domain.shell import _redact_command_for_logging, run

logger = logging.getLogger(__name__)

# Suffix appended to curl argv so we can read the HTTP status from stdout.
# We put it on its own line so we can trivially split the response body
# from the status code without any extra parsing.
_HTTP_CODE_MARKER = '\n%{http_code}'


def _run_curl(argv: list[str]) -> subprocess.CompletedProcess:
    """Run ``curl`` capturing stdout so we can inspect the response.

    The caller is responsible for building ``argv``; this helper only adds
    the common flags we need for diagnostics (``-s``, ``-o -``,
    ``-w <http_code_marker>``). ``--fail-with-body`` is NOT used because we
    want to keep the exit code == 0 on HTTP errors and make the decision
    based on the captured status code; that way we can include the response
    body in the error message even for 4xx/5xx.
    """
    full = ['curl', '-sS', '-o', '-', '-w', _HTTP_CODE_MARKER, *argv]
    # Echo the redacted command so the user sees what's being sent.
    typer.echo(f'Executing command: {" ".join(_redact_command_for_logging(full))}')
    return subprocess.run(
        full,
        check=False,
        text=True,
        capture_output=True,
    )


def _parse_curl_response(
    result: subprocess.CompletedProcess,
) -> tuple[int, str]:
    """Split ``curl`` stdout into ``(http_code, body)``.

    ``curl -w '\\n%{http_code}'`` appends the status code on its own line
    at the end of stdout. If for some reason the suffix is missing (e.g.
    curl failed to connect), we return ``(0, stdout + stderr)``.
    """
    output = (result.stdout or '').rstrip('\n')
    if '\n' not in output:
        # Probably a connection-level error; there is no http_code marker.
        body = (result.stdout or '') + (result.stderr or '')
        return 0, body.strip()
    body, _, code_str = output.rpartition('\n')
    try:
        return int(code_str.strip()), body
    except ValueError:
        return 0, output


def _check_http_response(action: str, result: subprocess.CompletedProcess) -> None:
    """Raise :class:`OdooCLIError` if the response is not a 2xx."""
    if result.returncode != 0 and not result.stdout:
        # curl failed before getting any response (network, TLS, DNS...).
        raise OdooCLIError(f'{action}: curl exited with {result.returncode}. stderr: {result.stderr.strip() or "<empty>"}')

    http_code, body = _parse_curl_response(result)
    if http_code == 0:
        raise OdooCLIError(f'{action}: could not parse HTTP response from Odoo. Raw output: {body[:500]}')
    if http_code >= 400:
        snippet = body.strip()
        if len(snippet) > 500:
            snippet = snippet[:500] + '...'
        raise OdooCLIError(f'{action}: Odoo returned HTTP {http_code}. Response body: {snippet or "<empty>"}')


def check_connection(client: ClientConfig) -> bool:
    """Return True if Odoo's HTTP endpoint at ``client.database.url`` is reachable."""
    url = client.database.url
    typer.echo(f'Checking connection to Odoo server at {url}...')
    result = run(
        ['curl', '-Is', url],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def restore_database(client: ClientConfig, backup_file: str = 'upgraded.zip') -> None:
    """POST ``backup_file`` to ``/web/database/restore`` and validate the HTTP status."""
    db_name = client.database.db_name
    master_pwd = client.database.master_pwd
    url = client.database.url

    typer.echo(f'POST {url}/web/database/restore (db={db_name})')

    try:
        result = _run_curl(
            [
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
            ]
        )
    except FileNotFoundError as err:
        raise OdooCLIError(f'curl is not installed on this host: {err}') from err

    _check_http_response(f'Database {db_name} restore', result)
    typer.echo(f'Database {db_name} restored successfully')


def drop_database(client: ClientConfig) -> None:
    """POST to ``/web/database/drop`` and validate the HTTP status."""
    db_name = client.database.db_name
    master_pwd = client.database.master_pwd
    url = client.database.url

    typer.echo(f'POST {url}/web/database/drop (db={db_name})')

    try:
        result = _run_curl(
            [
                '-X',
                'POST',
                '-F',
                f'master_pwd={master_pwd}',
                '-F',
                f'name={db_name}',
                f'{url}/web/database/drop',
            ]
        )
    except FileNotFoundError as err:
        raise OdooCLIError(f'curl is not installed on this host: {err}') from err

    _check_http_response(f'Database {db_name} drop', result)
    typer.echo(f'Database {db_name} dropped successfully')


def get_database_list(client: ClientConfig) -> list[str]:
    """List the databases visible to the Odoo container via ``odoo-bin --list``.

    Note: This runs inside ``client.docker.db_container`` but invokes
    ``/mnt/odoo/odoo-bin``, which assumes a specific container layout. This
    is a pre-existing caveat from the original implementation.
    """
    container_name = client.docker.db_container
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


def check_odoo_container_connection(client: ClientConfig) -> bool:
    """Return True if the Odoo container can reach its own database manager."""
    container_name = client.docker.db_container
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
