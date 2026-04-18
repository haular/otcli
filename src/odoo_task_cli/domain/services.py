"""
Utility functions for executing commands.
"""

import logging
import subprocess

import typer

from odoo_task_cli.domain.exceptions import OdooCLIError

logger = logging.getLogger(__name__)


def run(
    command: list[str], check: bool = True, text: bool = True, stdout: int | None = None, stderr: int | None = None
) -> subprocess.CompletedProcess:
    """
    Execute a command and return the result.

    Args:
        command: List of command arguments
        check: If True, raise an exception if the command fails
        text: If True, decode stdout and stderr as text
        stdout: Subprocess stdout option
        stderr: Subprocess stderr option

    Returns:
        CompletedProcess instance with the command result

    Raises:
        SystemExit: If the command fails and check is True
    """
    try:
        typer.echo(f'Executing command: {" ".join(command)}')
        result = subprocess.run(command, check=check, text=text, stdout=stdout, stderr=stderr)
        return result
    except subprocess.CalledProcessError as e:
        logger.exception(f'Command execution failed: {" ".join(command)}')
        if check:
            raise OdooCLIError(f'Command execution failed: {e}')
        raise
