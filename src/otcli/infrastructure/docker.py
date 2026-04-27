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

import json
import logging
import shlex
import subprocess
from dataclasses import dataclass

import typer

from otcli.domain.exceptions import ContainerNotFoundError, OdooCLIError
from otcli.domain.shell import run

logger = logging.getLogger(__name__)

# Common locations where Odoo's odoo.conf may live inside a container.
_DEFAULT_ODOO_CONF_PATHS: tuple[str, ...] = (
    '/etc/odoo/odoo.conf',
    '/etc/odoo.conf',
    '/etc/odoo/openerp-server.conf',
)


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


@dataclass(slots=True, frozen=True)
class ContainerMount:
    """A single bind-mount or named volume on a container.

    ``source`` is the host-side path (for ``bind``) or the volume name
    (for ``volume``). ``destination`` is the in-container path.
    For named volumes, ``host_path`` carries the actual host path that
    Docker uses to back the volume (``/var/lib/docker/volumes/<name>/_data``)
    so callers can use either depending on what they need.
    """

    type: str
    source: str
    destination: str
    host_path: str


def list_container_mounts(container_name: str) -> list[ContainerMount]:
    """Return all mounts (binds + named volumes) of ``container_name``.

    Uses ``docker inspect`` and parses the ``Mounts`` array. Returns an
    empty list if the container does not exist or docker is unavailable.
    """
    try:
        proc = subprocess.run(
            ['docker', 'inspect', container_name],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        logger.error('docker is not installed.')
        return []
    if proc.returncode != 0:
        logger.error('docker inspect failed for %s: %s', container_name, proc.stderr.strip())
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as err:
        logger.error('Could not parse docker inspect output: %s', err)
        return []
    if not data:
        return []
    raw_mounts = data[0].get('Mounts', []) or []
    mounts: list[ContainerMount] = []
    for m in raw_mounts:
        m_type = m.get('Type', '')
        source = m.get('Name') if m_type == 'volume' else m.get('Source', '')
        host_path = m.get('Source', '')  # always the actual host path
        destination = m.get('Destination', '')
        mounts.append(
            ContainerMount(
                type=m_type,
                source=source or '',
                destination=destination,
                host_path=host_path,
            )
        )
    return mounts


def read_file_from_container(container_name: str, path: str) -> str | None:
    """Return the contents of ``path`` inside ``container_name`` as text.

    Uses ``docker exec ... cat <path>``. Returns ``None`` if the file
    does not exist or cannot be read; we deliberately do not raise so
    callers can probe several candidate paths.
    """
    try:
        proc = subprocess.run(
            ['docker', 'exec', container_name, 'cat', path],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def find_odoo_conf_in_container(container_name: str) -> tuple[str, str] | None:
    """Locate an Odoo configuration file inside ``container_name``.

    Tries a small list of well-known paths via ``cat`` (cheap; failed
    reads cost nothing) and returns the first hit. The returned tuple
    is ``(path_inside_container, file_contents)``.

    Returns ``None`` if no candidate yielded a readable file.
    """
    for candidate in _DEFAULT_ODOO_CONF_PATHS:
        contents = read_file_from_container(container_name, candidate)
        if contents is not None:
            return candidate, contents
    return None


def parse_data_dir_from_odoo_conf(contents: str) -> str | None:
    """Extract the ``data_dir`` value from a parsed odoo.conf string.

    The Odoo config file is INI-like; we look for the first uncommented
    ``data_dir = <value>`` line. Returns ``None`` if absent.
    """
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        if key.strip() == 'data_dir':
            return value.strip()
    return None


def map_container_path_to_host(container_name: str, container_path: str) -> str | None:
    """Translate ``container_path`` into a host path using the container's mounts.

    Picks the longest matching mount destination so that nested mounts
    are handled correctly. Returns ``None`` if no mount covers the path.
    """
    if not container_path:
        return None
    mounts = list_container_mounts(container_name)
    best: ContainerMount | None = None
    for m in mounts:
        if not m.destination:
            continue
        is_match = container_path == m.destination or container_path.startswith(m.destination.rstrip('/') + '/')
        if is_match and (best is None or len(m.destination) > len(best.destination)):
            best = m
    if best is None:
        return None
    suffix = container_path[len(best.destination) :].lstrip('/')
    if not best.host_path:
        return None
    return best.host_path.rstrip('/') + ('/' + suffix if suffix else '')


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
