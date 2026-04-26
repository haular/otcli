"""Run ``odoo-bin neutralize`` against a freshly-restored test database.

The Odoo upgrade docs recommend neutralising any test database before
exposing it to a developer or CI runner: this disables outbound emails,
external integrations, scheduled actions, and similar side effects.

Usage from the restore service:

    from otcli.infrastructure.neutralize import neutralize_database

    if client.upgrade.environment == 'test':
        try:
            neutralize_database(client)
        except NeutralizeError as err:
            logger.warning('Neutralize failed: %s', err)

The module deliberately fails *soft*: when neutralization fails, the
restore is still considered successful and the caller is expected to
log a WARNING. Production environments must never go through this
helper (the caller is responsible for the gate).
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from collections.abc import Iterable

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import NeutralizeError

logger = logging.getLogger(__name__)


# Candidate paths probed inside the Odoo container when the user has
# not configured ``docker.odoo_bin_path``. Order matters: we prefer the
# user's PATH (covers the official Debian package and most custom
# images), then well-known mount points.
_AUTO_DETECT_CANDIDATES: tuple[str, ...] = (
    'odoo-bin',  # resolved by 'which' inside the container
    '/usr/bin/odoo-bin',
    '/mnt/odoo/odoo-bin',
    '/opt/odoo/odoo-bin',
)


def _docker_exec(container: str, argv: Iterable[str]) -> subprocess.CompletedProcess:
    """Run ``argv`` inside ``container`` and return the completed process."""
    full = ['docker', 'exec', container, *argv]
    return subprocess.run(full, check=False, capture_output=True, text=True)


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


def _resolve_odoo_bin(client: ClientConfig) -> str:
    """Return the absolute path of ``odoo-bin`` inside the Odoo container.

    Resolution order:
      1. ``client.docker.odoo_bin_path`` if non-empty.
      2. ``which odoo-bin`` inside the container.
      3. The hard-coded fallbacks ``/usr/bin/odoo-bin``,
         ``/mnt/odoo/odoo-bin``, ``/opt/odoo/odoo-bin``.

    Raises:
        NeutralizeError: if the configured path is not executable or
            none of the auto-detect candidates work. The error message
            instructs the user to set ``docker.odoo_bin_path`` and
            re-run.
    """
    container = client.docker.odoo_container

    explicit = client.docker.odoo_bin_path
    if explicit:
        if not _path_is_executable_in_container(container, explicit):
            raise NeutralizeError(
                f'Configured docker.odoo_bin_path={explicit!r} is not executable '
                f'inside container {container!r}. Update the value with '
                f"'otcli config edit'."
            )
        return explicit

    for candidate in _AUTO_DETECT_CANDIDATES:
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
        f'Tried: {", ".join(_AUTO_DETECT_CANDIDATES)}. '
        f"Configure docker.odoo_bin_path with 'otcli config edit'."
    )


def neutralize_database(client: ClientConfig) -> None:
    """Run ``odoo-bin neutralize -d <db_name>`` inside the Odoo container.

    Pre-conditions (caller responsibility):
      - ``client.upgrade.environment == 'test'``.
      - ``client.docker.odoo_container`` is set.
      - The Odoo container is running.

    Raises:
        NeutralizeError: if odoo-bin cannot be located or the
            neutralization command exits non-zero. The error message
            includes the captured stderr (truncated to 500 chars).
    """
    if not client.docker.odoo_container:
        raise NeutralizeError("docker.odoo_container is empty; cannot neutralize. Configure it with 'otcli config edit'.")

    odoo_bin = _resolve_odoo_bin(client)
    db_name = client.database.db_name or client.technical_name

    logger.info(
        'Neutralizing database %s via %s in container %s',
        db_name,
        odoo_bin,
        client.docker.odoo_container,
    )

    proc = _docker_exec(
        client.docker.odoo_container,
        [odoo_bin, 'neutralize', '-d', db_name],
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or '').strip()
        if len(stderr) > 500:
            stderr = stderr[:500] + '...'
        raise NeutralizeError(
            f'odoo-bin neutralize -d {db_name} exited with code {proc.returncode}. '
            f'Output: {stderr or "<empty>"}. '
            f'Command: {shlex.join([odoo_bin, "neutralize", "-d", db_name])}'
        )


__all__ = ['NeutralizeError', 'neutralize_database']
