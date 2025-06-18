"""
Functions for backing up Odoo databases.
"""
import datetime
import logging
import os
import shutil
import sys

import typer
from odoo_task_cli.app_config import config
from odoo_task_cli.infrastructure.docker_client import _get_container, _exec_in_container, _copy_file_from_container

logger = logging.getLogger(__name__)


def _backup_database(output_path: str) -> str:
    db_name = config.db_name
    container_name = config.db_container_name

    backup_file = "dump.sql"
    temp_path = f"/tmp/{backup_file}"
    final_path = os.path.join(output_path, backup_file)

    typer.echo(f"Backing up database {db_name} from container {container_name}...")

    # Get container
    container = _get_container(container_name)

    # Execute pg_dump in container
    typer.echo("Executing pg_dump...")
    _exec_in_container(container, f"pg_dump -U odoo --no-owner -d {db_name} -f dump.sql")

    # Copy backup file from container to host
    typer.echo("Copying backup file from container...")
    _copy_file_from_container(container_name, backup_file, temp_path)

    # Move backup file to final destination
    shutil.move(temp_path, final_path)

    # Remove backup file from container
    _exec_in_container(container, f"rm {backup_file}")

    # Verify backup file
    if os.path.getsize(final_path) == 0:
        typer.echo(
            f"Error: The generated backup file {final_path} is empty. "
            f"Please verify that the selected database is correct."
        )
        sys.exit(1)

    typer.echo(f"Database backup completed: {final_path}")
    return final_path


def _copy_filestore(output_path: str) -> str:
    filestore_path = config.filestore_dir

    typer.echo(f"Copying filestore from {filestore_path}...")

    # Create filestore directory
    filestore_dir = os.path.join(output_path, "filestore")
    os.makedirs(filestore_dir, exist_ok=True)

    # Copy filestore
    shutil.copytree(filestore_path, filestore_dir, dirs_exist_ok=True)

    typer.echo(f"Filestore copied to {filestore_dir}")
    return filestore_dir


def _compress_backup(backup_name: str, output_path: str) -> str:
    typer.echo("Compressing backup...")

    # Create zip file
    zip_file = shutil.make_archive(backup_name, "zip", output_path)

    typer.echo(f"Backup compressed: {zip_file}")
    return zip_file


def backup_odoo(with_filestore: bool) -> None:
    db_name = config.db_name
    output_path = config.client_backup_dir
    today = datetime.datetime.now().strftime("%d_%m_%Y")
    backup_name = f"{db_name}_{today}"

    # Create a temporary directory for the backup
    temp_dir = os.path.join(output_path, "temp_backup")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # Step 1: Backup database
        _backup_database(temp_dir)

        # Step 2: Handle filestore
        if with_filestore:
            _copy_filestore(temp_dir)
        else:
            # Create an empty filestore directory
            os.makedirs(os.path.join(temp_dir, "filestore"), exist_ok=True)
            typer.echo("Created an empty filestore directory as requested.")

        # Step 3: Compress backup
        zip_file = _compress_backup(backup_name, temp_dir)

        # Move zip file to output path
        shutil.move(zip_file, os.path.join(output_path, os.path.basename(zip_file)))

    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir)

    typer.echo("Odoo backup process completed successfully.")
