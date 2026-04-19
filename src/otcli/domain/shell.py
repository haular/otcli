"""Thin wrapper around :mod:`subprocess` with credential-aware logging."""

from __future__ import annotations

import logging
import re
import subprocess

import typer

from otcli.domain.exceptions import OdooCLIError

logger = logging.getLogger(__name__)

# Keys whose value must never appear in logs. Matched case-insensitively
# against the left-hand side of ``key=value`` arguments (e.g. curl -F args
# or ``KEY=value`` env-style prefixes).
_SECRET_KEY_PATTERN = re.compile(
    r'(?i)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)',
)

_REDACTED = '***REDACTED***'


def _redact_command_for_logging(command: list[str]) -> list[str]:
    """Return a copy of ``command`` with credential values masked.

    Any argument shaped like ``KEY=value`` whose KEY matches a known
    credential name (``password``, ``pwd``, ``secret``, ``token``,
    ``api_key``, ``access_key``, case-insensitive) has its value replaced
    by a fixed placeholder. All other arguments pass through unchanged.

    The original list is never mutated.
    """
    redacted: list[str] = []
    for arg in command:
        if '=' in arg:
            key, _, _value = arg.partition('=')
            if _SECRET_KEY_PATTERN.search(key):
                redacted.append(f'{key}={_REDACTED}')
                continue
        redacted.append(arg)
    return redacted


def run(
    command: list[str],
    check: bool = True,
    text: bool = True,
    stdout: int | None = None,
    stderr: int | None = None,
) -> subprocess.CompletedProcess:
    """Execute ``command`` and return the completed process.

    Args:
        command: List of command arguments (argv).
        check: If True, raise :class:`OdooCLIError` on a non-zero exit code.
        text: If True, decode stdout/stderr as text.
        stdout: subprocess stdout option (e.g. ``subprocess.PIPE``).
        stderr: subprocess stderr option.

    Raises:
        OdooCLIError: On non-zero exit when ``check`` is True.
    """
    safe_command = _redact_command_for_logging(command)
    safe_str = ' '.join(safe_command)
    typer.echo(f'Executing command: {safe_str}')
    try:
        return subprocess.run(command, check=check, text=text, stdout=stdout, stderr=stderr)
    except subprocess.CalledProcessError as err:
        logger.exception('Command execution failed: %s', safe_str)
        if check:
            raise OdooCLIError(f'Command execution failed: {err}') from err
        raise
