"""Run ``odoo-bin neutralize`` against a freshly-restored test database.

The Odoo upgrade docs recommend neutralising any test database before
exposing it to a developer or CI runner: this disables outbound emails,
external integrations, scheduled actions, and similar side effects.

This module supports the three Odoo deployment topologies otcli targets:

* **docker**: Odoo runs in a container; we ``docker exec <container>
  <odoo-bin> neutralize -d <db>``. ``odoo-bin`` is auto-detected inside
  the container if not configured explicitly.

* **native**: Odoo is installed on the host (Debian package or similar);
  we run ``<odoo-bin> neutralize -d <db>`` on the host. ``odoo-bin`` is
  auto-detected via ``which odoo-bin`` then ``/usr/bin/odoo-bin``.

* **source**: Odoo was cloned from GitHub onto the host; the user must
  provide ``odoo.odoo_bin_path`` pointing at the script in the clone.
  We run it directly on the host with whatever interpreter the script's
  shebang specifies.

Failures of this helper raise :class:`NeutralizeError`. The caller (the
restore service) is expected to log the error at WARNING and return
normally so users notice but the restore exits 0.
"""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import NeutralizeError

logger = logging.getLogger(__name__)


# Candidate paths probed inside the Odoo container when the user has
# not configured ``odoo.odoo_bin_path`` and ``install_mode == 'docker'``.
# Order matters: prefer the user's PATH, then well-known mount points.
_DOCKER_AUTO_DETECT_CANDIDATES: tuple[str, ...] = (
    'odoo-bin',  # resolved by 'which' inside the container
    '/usr/bin/odoo-bin',
    '/mnt/odoo/odoo-bin',
    '/opt/odoo/odoo-bin',
)

# Candidate paths probed on the host when ``install_mode == 'native'``.
_NATIVE_HOST_CANDIDATES: tuple[str, ...] = ('/usr/bin/odoo-bin',)


# --- low-level execution helpers -----------------------------------------


def _docker_exec(container: str, argv: Iterable[str]) -> subprocess.CompletedProcess:
    """Run ``argv`` inside ``container`` and return the completed process."""
    full = ['docker', 'exec', container, *argv]
    return subprocess.run(full, check=False, capture_output=True, text=True)


def _host_exec(argv: Iterable[str]) -> subprocess.CompletedProcess:
    """Run ``argv`` on the host and return the completed process."""
    return subprocess.run(list(argv), check=False, capture_output=True, text=True)


# --- path resolution ------------------------------------------------------


def _path_is_executable_in_container(container: str, path: str) -> bool:
    """Return True if ``path`` exists and is executable inside ``container``."""
    proc = _docker_exec(container, ['test', '-x', path])
    return proc.returncode == 0


def _which_in_container(container: str, name: str) -> str | None:
    """Return the resolved absolute path of ``name`` via ``which``, or None."""
    proc = _docker_exec(container, ['which', name])
    if proc.returncode != 0:
        return None
    candidate = proc.stdout.strip()
    return candidate or None


def _resolve_in_docker(client: ClientConfig) -> str:
    """Find ``odoo-bin`` inside the Odoo container."""
    container = client.odoo.container_name

    explicit = client.odoo.odoo_bin_path
    if explicit:
        if not _path_is_executable_in_container(container, explicit):
            raise NeutralizeError(
                f'Configured odoo.odoo_bin_path={explicit!r} is not executable '
                f'inside container {container!r}. Update the value with '
                f"'otcli config edit'."
            )
        return explicit

    for candidate in _DOCKER_AUTO_DETECT_CANDIDATES:
        if candidate == 'odoo-bin':
            resolved = _which_in_container(container, candidate)
            if resolved:
                logger.debug('Resolved odoo-bin via `which` to %s', resolved)
                return resolved
            continue
        if _path_is_executable_in_container(container, candidate):
            logger.debug('Resolved odoo-bin to fallback %s', candidate)
            return candidate

    raise NeutralizeError(
        f'odoo-bin not found inside container {container!r}. '
        f'Tried: {", ".join(_DOCKER_AUTO_DETECT_CANDIDATES)}. '
        f"Configure odoo.odoo_bin_path with 'otcli config edit'."
    )


def _resolve_native(client: ClientConfig) -> str:
    """Find ``odoo-bin`` on the host (native install)."""
    explicit = client.odoo.odoo_bin_path
    if explicit:
        if not Path(explicit).is_file() or not _is_executable(Path(explicit)):
            raise NeutralizeError(
                f'Configured odoo.odoo_bin_path={explicit!r} is not an '
                f"executable file on the host. Update it with 'otcli config edit'."
            )
        return explicit

    # 1. ``which odoo-bin`` on the host.
    via_which = shutil.which('odoo-bin')
    if via_which:
        logger.debug('Resolved odoo-bin via host `which` to %s', via_which)
        return via_which

    # 2. Hard-coded fallbacks.
    for candidate in _NATIVE_HOST_CANDIDATES:
        path = Path(candidate)
        if path.is_file() and _is_executable(path):
            logger.debug('Resolved odoo-bin to host fallback %s', candidate)
            return candidate

    raise NeutralizeError(
        'odoo-bin not found on host. '
        f'Tried `which odoo-bin` and {", ".join(_NATIVE_HOST_CANDIDATES)}. '
        f"Set odoo.odoo_bin_path with 'otcli config edit'."
    )


def _resolve_source(client: ClientConfig) -> str:
    """Validate ``odoo-bin`` for a clone-from-source install."""
    explicit = client.odoo.odoo_bin_path
    if not explicit:
        raise NeutralizeError(
            "odoo.odoo_bin_path is required when install_mode='source'. "
            "Set it with 'otcli config edit' to point at the odoo-bin "
            'script inside your Odoo clone.'
        )
    path = Path(explicit)
    if not path.is_file() or not _is_executable(path):
        raise NeutralizeError(
            f'Configured odoo.odoo_bin_path={explicit!r} is not an '
            f"executable file on the host. Update it with 'otcli config edit'."
        )
    return explicit


def _is_executable(path: Path) -> bool:
    """Return True if ``path`` exists and the current user can execute it."""
    import os

    return path.exists() and os.access(path, os.X_OK)


# --- public API ----------------------------------------------------------


def _build_neutralize_argv(
    odoo_bin: str,
    db_name: str,
    conf_path: str,
    python_executable: str = '',
) -> list[str]:
    """Build the argv for ``odoo-bin neutralize``.

    Argument layout (Odoo 16+):

        [<python_executable>] <odoo_bin> neutralize [-c <conf>] -d <db>

    The ``neutralize`` subcommand MUST come immediately after
    ``odoo-bin``: anything before it is parsed by the top-level option
    parser, which doesn't know about ``neutralize`` and aborts with
    ``unrecognized parameters``. Per-subcommand options (``-c``, ``-d``)
    follow the subcommand.

    When ``python_executable`` is provided, it is prepended so that the
    interpreter is chosen explicitly instead of relying on ``odoo-bin``'s
    shebang (``#!/usr/bin/env python3``). This is the typical fix for
    source installs where Odoo's runtime dependencies live in a venv.
    """
    argv: list[str] = []
    if python_executable:
        argv.append(python_executable)
    argv.append(odoo_bin)
    argv.append('neutralize')
    if conf_path:
        argv.extend(['-c', conf_path])
    argv.extend(['-d', db_name])
    return argv


def _validate_python_executable(path: str) -> None:
    """Raise :class:`NeutralizeError` if ``path`` is set but unusable."""
    if not path:
        return
    p = Path(path)
    if not p.is_file() or not _is_executable(p):
        raise NeutralizeError(
            f'Configured odoo.python_executable={path!r} is not an '
            f"executable file on the host. Update it with 'otcli config edit'."
        )


def neutralize_database(client: ClientConfig) -> None:
    """Run ``odoo-bin neutralize -d <db_name>`` against ``client``.

    Dispatches on ``client.odoo.install_mode``:

    * ``docker``: ``docker exec <container> <odoo-bin> neutralize -d <db>``.
      The container's embedded configuration is used; ``odoo_conf_path``
      is ignored.
    * ``native``: ``<odoo-bin> [-c <conf>] neutralize -d <db>`` on the
      host. ``-c`` is added when ``odoo_conf_path`` is configured.
    * ``source``: ``<odoo-bin> -c <conf> neutralize -d <db>`` on the
      host. Both bin and conf paths are required (validated upstream).

    Pre-conditions (caller responsibility):
      - ``client.upgrade.environment == 'test'``.
      - For docker mode, the Odoo container is running.

    Raises:
        NeutralizeError: if odoo-bin cannot be located or the
            neutralization command exits non-zero. The error message
            includes the captured stderr (truncated to 500 chars).
    """
    mode = client.odoo.install_mode
    db_name = client.database.db_name or client.technical_name

    if mode == 'docker':
        if not client.odoo.container_name:
            raise NeutralizeError("odoo.container_name is empty; cannot neutralize. Configure it with 'otcli config edit'.")
        odoo_bin = _resolve_in_docker(client)
        # In docker mode the container ships its own config; we never
        # forward odoo_conf_path even if it's set on the client.
        argv = _build_neutralize_argv(odoo_bin, db_name, conf_path='')
        logger.info(
            'Neutralizing database %s via %s in container %s',
            db_name,
            odoo_bin,
            client.odoo.container_name,
        )
        proc = _docker_exec(client.odoo.container_name, argv)
        rendered = f'docker exec {client.odoo.container_name} {shlex.join(argv)}'
    elif mode == 'native':
        odoo_bin = _resolve_native(client)
        _validate_python_executable(client.odoo.python_executable)
        argv = _build_neutralize_argv(
            odoo_bin,
            db_name,
            conf_path=client.odoo.odoo_conf_path,
            python_executable=client.odoo.python_executable,
        )
        logger.info('Neutralizing database %s via host odoo-bin %s', db_name, odoo_bin)
        proc = _host_exec(argv)
        rendered = shlex.join(argv)
    elif mode == 'source':
        odoo_bin = _resolve_source(client)
        _validate_python_executable(client.odoo.python_executable)
        # Schema validation guarantees odoo_conf_path is set in 'source'.
        argv = _build_neutralize_argv(
            odoo_bin,
            db_name,
            conf_path=client.odoo.odoo_conf_path,
            python_executable=client.odoo.python_executable,
        )
        logger.info('Neutralizing database %s via source odoo-bin %s', db_name, odoo_bin)
        proc = _host_exec(argv)
        rendered = shlex.join(argv)
    else:  # pragma: no cover - guarded by ClientConfig validation
        raise NeutralizeError(f'Unknown install_mode {mode!r}')

    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or '').strip()
        if len(stderr) > 500:
            stderr = stderr[:500] + '...'
        raise NeutralizeError(
            f'odoo-bin neutralize -d {db_name} exited with code {proc.returncode}. '
            f'Output: {stderr or "<empty>"}. Command: {rendered}'
        )


__all__ = ['NeutralizeError', 'neutralize_database']
