"""Utility functions for Git operations.

Currently unused by the CLI commands but kept for future upgrade tooling that
needs to check out a specific commit before running migrations.
"""

import logging
import os

import typer
from git import GitCommandError, Repo

from odoo_task_cli.config import config
from odoo_task_cli.domain.exceptions import GitCheckoutError, OdooCLIError

logger = logging.getLogger(__name__)


def _get_repo(repo_path: str) -> Repo:
    """Get a :class:`git.Repo` instance for ``repo_path``.

    Raises:
        OdooCLIError: If the path does not exist or is not a valid git repo.
    """
    if not os.path.exists(repo_path):
        raise OdooCLIError(f"Git repository path '{repo_path}' does not exist.")

    try:
        return Repo(repo_path)
    except Exception as err:
        typer.echo(f"Error: Failed to open Git repository at '{repo_path}'")
        logger.exception("Failed to open Git repository at '%s'", repo_path)
        raise OdooCLIError(f"Failed to open Git repository at '{repo_path}': {err}") from err


def _checkout_commit(commit_hash: str) -> None:
    """Check out ``commit_hash`` in the repository configured as
    ``config.repo_path``.

    Raises:
        OdooCLIError: If the repository cannot be opened.
        GitCheckoutError: If the checkout itself fails.
    """
    repo_path = config.repo_path
    try:
        repo = Repo(repo_path)
    except Exception as err:
        typer.echo(f'Error: Failed to open Git repository at {repo_path}: {err}')
        logger.error('Failed to open Git repository at %s: %s', repo_path, err)
        raise OdooCLIError(f'Git repository at {repo_path} does not exist') from err

    try:
        typer.echo(f'Checking out commit: {commit_hash}')
        repo.git.checkout(commit_hash)
    except GitCommandError as err:
        raise GitCheckoutError(f"Error: Failed to checkout commit '{commit_hash}': {err}") from err
