import logging
import os
import shutil
import subprocess
import sys
import zipfile
from typing import List

import typer
from odoo_task_cli.app_config import config
from odoo_task_cli.domain.services import run
from odoo_task_cli.infrastructure.docker_client import _get_container, _copy_file_to_container, _exec_in_container

logger = logging.getLogger(__name__)


def check_connection() -> bool:
    url = config.url

    typer.echo(f"Checking connection to Odoo server at {url}...")

    result = run(
        ["curl", "-Is", url],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return result.returncode == 0


def restore_database(backup_file: str = "upgraded.zip") -> None:
    db_name = config.db_name
    master_pwd = config.master_pwd
    url = config.url

    typer.echo(
        "Executing POST request to restore the database:"
        f"\n - Database name: {db_name}"
        f"\n - URL: {url}"
    )

    run(
        [
            "curl",
            "-X",
            "POST",
            "-F",
            f"master_pwd={master_pwd}",
            "-F",
            f"name={db_name}",
            "-F",
            "copy=false",
            "-F",
            "neutralize_database=false",
            "-F",
            f"backup_file=@{backup_file}",
            f"{url}/web/database/restore",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    typer.echo(f"Database {db_name} restored successfully")


def drop_database() -> None:
    db_name = config.db_name
    master_pwd = config.master_pwd
    url = config.url

    typer.echo(f"Dropping database {db_name}...")
    run(
        [
            "curl",
            "-X",
            "POST",
            "-F",
            f"master_pwd={master_pwd}",
            "-F",
            f"name={db_name}",
            f"{url}/web/database/drop",
        ]
        , check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    typer.echo(f"Database {db_name} dropped successfully")


def get_database_list() -> List[str]:
    container_name = config.db_container_name
    """
    Get a list of databases from Odoo.

    Returns:
        List of database names

    Raises:
        SystemExit: If the operation fails
    """
    try:
        command = [
            "docker",
            "exec",
            container_name,
            "/mnt/odoo/odoo-bin",
            "-c",
            "/etc/odoo/odooshell.conf",
            "--list",
        ]
        result = run(command)

        # Parse the output to get the database list
        output = result.stdout.strip()
        if not output:
            return []

        # Skip the header line and get the database names
        lines = output.split("\n")
        if len(lines) > 1:
            return [line.strip() for line in lines[1:] if line.strip()]
        return []
    except Exception:
        typer.echo("Failed to get database list.")
        logger.exception("Failed to get database list")
        sys.exit(1)


def download_upgrade_script() -> str:
    """
    Download the Odoo upgrade script.

    Returns:
        Path to the downloaded script
    """
    typer.echo("Downloading Odoo upgrade script...")
    run(
        [
            "curl",
            "https://upgrade.odoo.com/upgrade",
            "-o",
            "odoo-upgrade.py",
        ]
    )
    return "odoo-upgrade.py"


def run_upgrade(backup_file: str) -> str:
    code_subscription = config.code_subscription
    target_version = config.upgrade_target
    environment = config.environment

    logger.info(f"Running Odoo upgrade service for {backup_file}...")
    logger.info(f"Target version: {config.odoo.upgrade_target}")

    # Download upgrade script if it doesn't exist
    upgrade_script = download_upgrade_script()

    # Run upgrade
    run(
        [
            "python3",
            upgrade_script,
            environment,
            "-i",
            backup_file,
            "-c",
            code_subscription,
            "-t",
            target_version,
        ]
    )

    # Clean up
    os.remove(upgrade_script)

    return "upgraded.zip"


def check_existing_upgrade(backup_file) -> bool:
    """
    Check if an upgraded database file already exists.

    Returns:
        True if an upgraded file exists, False otherwise
    """
    return os.path.exists(backup_file + '/upgraded.zip')


def check_odoo_container_connection() -> bool:
    container_name = config.db_container_name
    try:
        command = [
            "docker",
            "exec",
            container_name,
            "curl",
            "-s",
            "http://localhost:8069/web/database/manager",
        ]
        result = run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except Exception:
        logger.exception("Failed to check Odoo container connection")
        return False


def restore_database_from_container(backup_file: str) -> None:
    target_db_container_name = config.docker.db_container_name
    target_db_name = config.docker.db_name
    target_filestore_dir = config.odoo.filestore_dir

    temp_extract_dir = "./temp_extracted_backup"
    os.makedirs(temp_extract_dir, exist_ok=True)

    with zipfile.ZipFile(backup_file, 'r') as zip_ref:
        zip_ref.extractall(temp_extract_dir)

    dump_sql_path_host = os.path.join(temp_extract_dir, "dump.sql")
    filestore_path_host = os.path.join(temp_extract_dir, "filestore")

    # Restore dump.sql
    logger.info(f"Restoring database {target_db_name} in container {target_db_container_name}...")
    _copy_file_to_container(target_db_container_name, dump_sql_path_host, "/tmp/dump.sql")

    container = _get_container(target_db_container_name)

    _exec_in_container(container, f"dropdb -U odoo {target_db_name}", False)
    _exec_in_container(container, f"createdb -U odoo {target_db_name}")
    _exec_in_container(container, f"psql -U odoo -d {target_db_name} -f /tmp/dump.sql")
    _exec_in_container(container, "rm /tmp/dump.sql")

    logger.info(f"Database {target_db_name} restored successfully.")

    # Restore filestore
    if os.path.exists(filestore_path_host):
        logger.info(f"Copying filestore to {target_filestore_dir}...")
        if os.path.exists(target_filestore_dir):
            shutil.rmtree(target_filestore_dir)
        shutil.copytree(filestore_path_host, target_filestore_dir)
        logger.info("Filestore copied successfully.")
    else:
        logger.info("No filestore found in backup, skipping filestore restoration.")

    shutil.rmtree(temp_extract_dir)
