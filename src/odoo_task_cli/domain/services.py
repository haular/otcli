"""
Utility functions for executing commands.
"""
import logging
import subprocess
import sys
from typing import List, Optional

import typer

logger = logging.getLogger(__name__)


def run(command: List[str], check: bool = True, text: bool = True,
        stdout: Optional[int] = None, stderr: Optional[int] = None) -> subprocess.CompletedProcess:
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
        typer.echo(f"Executing command: {' '.join(command)}")
        result = subprocess.run(
            command,
            check=check,
            text=text,
            stdout=stdout,
            stderr=stderr
        )
        return result
    except subprocess.CalledProcessError:
        logger.exception(f"Command execution failed: {' '.join(command)}")
        if check:
            sys.exit(1)
        raise
