"""Docker helpers backed by the ``docker`` CLI via :mod:`subprocess`.

Earlier versions of otcli depended on the ``docker`` Python SDK (which
in turn pulls in ``requests``, ``urllib3``, ``websocket-client``, …).
We only ever used three operations: get a running container, exec a
command inside it, and copy files in and out. All three are trivially
expressible as ``docker`` CLI calls, so the SDK adds disproportionate
weight for a small CLI tool. This module replaces it with thin
subprocess wrappers and removes the runtime dependency entirely.

The public functions keep the same names and signatures so the rest of
the codebase (and the existing test suite) does not need to change.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass

import typer

from otcli.domain.exceptions import ContainerNotFoundError, OdooCLIError
from otcli.domain.shell import run

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ContainerHandle:
    """Lightweight stand-in for the previous ``docker.models.containers.Container``.

    Exposes just enough of the SDK's surface for our callers — namely
    ``exec_run`` returning a value with ``exit_code`` and ``output``.
    """

    name: str

    def exec_run(self, command: str) -> _ExecResult:
        argv = ['docker', 'exec', self.name, *shlex.split(command)]
        proc = subprocess.run(argv, check=False, capture_output=True)
        # Mimic the SDK's behaviour: stdout and stderr concatenated as
        # the ``output`` byte-string. Use stderr only when stdout is
        # empty so successful runs stay clean.
        output = proc.stdout if proc.stdout else proc.stderr
        return _ExecResult(exit_code=proc.returncode, output=output or b'')


@dataclass(slots=True)
class _ExecResult:
    exit_code: int
    output: bytes


def _get_container(container_name: str) -> _ContainerHandle:
    """Verify that ``container_name`` exists and is running, then return a handle."""
    try:
        proc = subprocess.run(
            ['docker', 'inspect', '--format={{.State.Status}}', container_name],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as err:
        raise OdooCLIError(f'docker is not installed on this host: {err}') from err

    if proc.returncode != 0:
        raise ContainerNotFoundError(f"Container '{container_name}' does not exist.")
    status = proc.stdout.strip()
    if status != 'running':
        raise ContainerNotFoundError(f"Container '{container_name}' is not running (status: {status}).")
    return _ContainerHandle(name=container_name)


def _copy_file_from_container(container_name: str, src_path: str, dest_path: str) -> None:
    """Copy a file from a Docker container to the host."""
    run(['docker', 'cp', f'{container_name}:{src_path}', dest_path])


def _copy_file_to_container(container_name: str, src_path: str, dest_path: str) -> None:
    """Copy a file from the host to a Docker container."""
    run(['docker', 'cp', src_path, f'{container_name}:{dest_path}'])


def _exec_in_container(
    container: _ContainerHandle,
    command: str,
    check: bool = True,
    **_legacy: object,
) -> _ExecResult:
    """Execute ``command`` inside ``container``.

    Args:
        container: Handle returned by :func:`_get_container`.
        command: Command string to execute. Parsed with ``shlex.split``.
        check: When ``True``, raise :class:`ContainerNotFoundError` on a
            non-zero exit code. When ``False``, the result is returned
            so the caller can decide what to do (used for best-effort
            invocations such as ``dropdb`` against a missing DB).

    Additional keyword arguments are accepted for backwards compatibility
    (the parameter used to be called ``sys_exit``) but ignored.
    """
    if 'sys_exit' in _legacy:
        check = bool(_legacy['sys_exit'])

    typer.echo(f'Executing in container: {command}')
    try:
        result = container.exec_run(command)
    except ContainerNotFoundError:
        raise
    except Exception as err:  # pragma: no cover - defensive
        raise ContainerNotFoundError(f'Error: Failed to execute command in container: {command}\n{err}') from err

    if result.exit_code != 0:
        output = result.output.decode('utf-8', errors='replace') if result.output else ''
        if check:
            raise ContainerNotFoundError(f'Error: Command execution failed in container: {command}\nOutput: {output}')
        logger.warning(
            'Non-zero exit (%s) from container command (ignored): %s\n%s',
            result.exit_code,
            command,
            output,
        )
    return result


def list_running_containers() -> list[str]:
    """Return the names of all currently-running Docker containers."""
    try:
        proc = subprocess.run(
            ['docker', 'ps', '--format={{.Names}}'],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as err:
        logger.error('docker is not installed: %s', err)
        return []
    if proc.returncode != 0:
        logger.error('docker ps failed: %s', proc.stderr.strip())
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def list_databases_in_container(container_name: str) -> list[str]:
    """List PostgreSQL databases reachable inside ``container_name`` via ``psql -l``."""
    container = _get_container(container_name)
    result = _exec_in_container(container, 'psql -U odoo -l -t -A', check=False)

    if result.exit_code != 0:
        raise ContainerNotFoundError(f"Error: could not list databases in container '{container_name}'.")

    output_lines = result.output.decode('utf-8', errors='replace').strip().split('\n')
    databases: list[str] = []
    for line in output_lines:
        parts = line.split('|')
        if not parts:
            continue
        db_name = parts[0].strip()
        if db_name and db_name not in {'template0', 'template1', 'postgres'}:
            databases.append(db_name)
    return databases
