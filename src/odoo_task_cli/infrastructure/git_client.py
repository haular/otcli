"""
Utility functions for Git operations.
"""
import logging
import os
import sys

import typer
from git import Repo, GitCommandError
from odoo_task_cli.app_config import config

logger = logging.getLogger(__name__)


def _get_repo(repo_path: str) -> Repo:
    """
    Get a Git repository instance.

    Args:
        repo_path: Path to the Git repository

    Returns:
        Repo instance

    Raises:
        SystemExit: If the repository doesn't exist
    """
    if not os.path.exists(repo_path):
        typer.echo(f"Error: Git repository path '{repo_path}' does not exist.")
        sys.exit(1)

    try:
        return Repo(repo_path)
    except Exception:
        typer.echo(f"Error: Failed to open Git repository at '{repo_path}'")
        logger.exception(f"Failed to open Git repository at '{repo_path}'")
        sys.exit(1)


def _checkout_commit(commit_hash: str) -> None:
    """
    Checkout a specific commit in a Git repository.

    Args:
        repo: Repo instance
        commit_hash: Commit hash to checkout

    Raises:
        SystemExit: If the checkout operation fails
    """
    try:
        repo = Repo(config.git)
    except Exception as e:
        typer.echo(f"Error: Failed to open Git repository at {config.git}: {e}")
        logger.error(f"Failed to open Git repository at {config.git}: {e}")
        raise FileNotFoundError(f"Git repository at {config.git} does not exist")

    try:
        typer.echo(f"Checking out commit: {commit_hash}")
        repo.git.checkout(commit_hash)
    except GitCommandError:
        typer.echo(f"Error: Failed to checkout commit '{commit_hash}'")
        logger.exception(f"Failed to checkout commit '{commit_hash}'")
        sys.exit(1)
