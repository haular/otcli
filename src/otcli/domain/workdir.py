"""Working-directory helper used by the backup pipeline."""

from __future__ import annotations

import logging
import os

import typer

from otcli.bootstrap import config

logger = logging.getLogger(__name__)


def setup_working_directory() -> None:
    """Ensure the CLI's configured working directory exists and ``cd`` into it.

    The path is taken from ``config.directory_path`` at call time so any
    mutation made after import is honoured.
    """
    directory_path = config.directory_path
    if not os.path.exists(directory_path):
        typer.echo(f'Warning: Directory {directory_path} does not exist. Creating directory...')
        os.makedirs(directory_path)
    os.chdir(directory_path)
    typer.echo(f'Working directory set to {directory_path}')
