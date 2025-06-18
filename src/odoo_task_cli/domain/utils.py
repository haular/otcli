"""
Common utility functions for the Odoo CLI tool.
"""
import logging
import os

import typer
from odoo_task_cli.app_config import config

logger = logging.getLogger(__name__)
DIRECTORY_PATH = config.directory_path


def setup_working_directory() -> None:
    directory_path = DIRECTORY_PATH
    # Create a directory even if it doesn't exist
    if not os.path.exists(directory_path):
        typer.echo(f"Warning: Directory {directory_path} does not exist. Creating directory...")
        os.makedirs(directory_path)
    # Change working directory
    os.chdir(directory_path)
    typer.echo(f"Working directory set to {directory_path}")

# def execute_commands(commands: Optional[List[Dict[str, Any]]] = None) -> None:
#     """
#     Execute a list of commands from the configuration.
#
#     Args:
#         commands: List of command dictionaries (defaults to COMMANDS)
#
#     Each command dictionary can have the following keys:
#         - hash: Git commit hash to checkout
#         - command: Command to execute
#     """
#     commands = commands or get_config('COMMANDS', [])
#
#     # Execute commands
#     for command in commands:
#         if "hash" in command:
#             _checkout_commit(command.get("hash"))
#         elif "command" in command:
#             run(command.get("command"))
#         else:
#             logger.warning(f"Skipping command with no 'hash' or 'command' key: {command}")
