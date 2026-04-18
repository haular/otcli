import json
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from typing import List

import typer

from odoo_task_cli.config import config
from odoo_task_cli.domain.exceptions import OdooCLIError
from odoo_task_cli.domain.services import run
from odoo_task_cli.infrastructure.docker_client import _get_container, _copy_file_to_container, _exec_in_container

logger = logging.getLogger(__name__)


def check_connection() -> bool:
    url = config.url

    typer.echo(f"Checking connection to Odoo server at {url}...")

    result = run(
        [
            "curl",
            "-Is",
            url
        ],
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
    except Exception as e:
        raise OdooCLIError(f"Failed to get database list: {e}")


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
    logger.info(f"Target version: {config.upgrade_target}")

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
    except Exception as e:
        raise OdooCLIError(f"Failed to check Odoo container connection: {e}")


def _validate_backup_zip(backup_file: str) -> None:
    """Fail fast if the zip does not look like an otcli backup.

    We require at least a ``dump.sql`` entry. The manifest is inspected when
    present but is not mandatory (older backups do not have one).
    """
    if not os.path.isfile(backup_file):
        raise OdooCLIError(f"Backup file not found: {backup_file}")

    try:
        with zipfile.ZipFile(backup_file, "r") as zf:
            names = set(zf.namelist())
            if "dump.sql" not in names:
                raise OdooCLIError(
                    f"Invalid backup: {backup_file} does not contain a 'dump.sql'."
                )
            if "manifest.json" in names:
                try:
                    manifest = json.loads(zf.read("manifest.json"))
                    if not manifest.get("has_dump", True):
                        raise OdooCLIError(
                            "Backup manifest reports no database dump present."
                        )
                except json.JSONDecodeError as err:
                    logger.warning("Ignoring unreadable manifest.json: %s", err)
    except zipfile.BadZipFile as err:
        raise OdooCLIError(f"Backup file is not a valid zip: {backup_file}") from err


def _verify_filestore_after_restore(
    extracted_filestore: str, final_path: str
) -> None:
    """Compare file counts between the extracted and final filestore dirs.

    Raises :class:`OdooCLIError` if any files appear to be missing after the
    move, unless ``OTCLI_FILESTORE_MISSING_TOLERANCE`` is set.
    """
    def _count(path: str) -> int:
        total = 0
        for _, _, files in os.walk(path, followlinks=False):
            total += len(files)
        return total

    # ``extracted_filestore`` may have been moved already; compute source count
    # before move if the caller passes the pre-move path.
    src_count = _count(extracted_filestore) if os.path.isdir(extracted_filestore) else 0
    dst_count = _count(final_path)
    tolerance = int(os.environ.get("OTCLI_FILESTORE_MISSING_TOLERANCE", "0"))

    # When called after the move, src_count == 0 and dst_count holds the moved
    # files; we compare against the manifest instead at the caller level.
    if src_count and (src_count - dst_count) > tolerance:
        raise OdooCLIError(
            f"Filestore restore verification failed: {src_count - dst_count} of "
            f"{src_count} files missing in {final_path}."
        )


def restore_database_from_container(backup_file: str) -> None:
    """Restore a database dump and its filestore into the configured target.

    Contract:
      * the target database does **not** need to exist up front; it will be
        (re)created;
      * the restore is aborted early if the backup zip is malformed;
      * temporary files are always cleaned up, even on failure;
      * ``psql`` is run with ``ON_ERROR_STOP=1`` so SQL errors surface as
        non-zero exit codes rather than producing a half-restored DB.
    """
    target_db_container_name = config.db_container_name
    target_db_name = config.db_name
    target_filestore_dir = config.filestore_dir

    _validate_backup_zip(backup_file)

    temp_extract_dir = tempfile.mkdtemp(prefix="otcli_restore_")

    try:
        with zipfile.ZipFile(backup_file, "r") as zip_ref:
            zip_ref.extractall(temp_extract_dir)

        dump_sql_path_host = os.path.join(temp_extract_dir, "dump.sql")
        filestore_path_host = os.path.join(temp_extract_dir, "filestore")

        # Load manifest if available for post-restore verification.
        manifest = {}
        manifest_path = os.path.join(temp_extract_dir, "manifest.json")
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as fh:
                    manifest = json.load(fh)
            except (OSError, json.JSONDecodeError) as err:
                logger.warning("Unable to parse manifest.json: %s", err)

        logger.info(
            "Restoring database %s in container %s...",
            target_db_name,
            target_db_container_name,
        )
        _copy_file_to_container(
            target_db_container_name, dump_sql_path_host, "/tmp/dump.sql"
        )

        container = _get_container(target_db_container_name)

        # dropdb is best-effort: the target database may not exist yet. We use
        # --if-exists *and* check=False for maximum robustness across
        # PostgreSQL versions.
        _exec_in_container(
            container,
            f"dropdb -U odoo --if-exists {target_db_name}",
            check=False,
        )
        _exec_in_container(container, f"createdb -U odoo {target_db_name}")
        # ``sh -c`` so ``ON_ERROR_STOP=1`` is interpreted as a psql variable.
        _exec_in_container(
            container,
            (
                f"sh -c 'psql -U odoo -v ON_ERROR_STOP=1 "
                f"-d {target_db_name} -f /tmp/dump.sql'"
            ),
        )
        _exec_in_container(container, "rm -f /tmp/dump.sql", check=False)

        logger.info("Database %s restored successfully.", target_db_name)

        # Restore filestore.
        if os.path.isdir(filestore_path_host) and any(os.scandir(filestore_path_host)):
            final_filestore_path = os.path.join(target_filestore_dir, target_db_name)
            os.makedirs(target_filestore_dir, exist_ok=True)

            logger.info(
                "Moving extracted filestore to final destination: %s",
                final_filestore_path,
            )

            # Count source files *before* moving (shutil.move will remove src).
            src_count = 0
            for _, _, files in os.walk(filestore_path_host, followlinks=False):
                src_count += len(files)

            if os.path.exists(final_filestore_path):
                shutil.rmtree(final_filestore_path)

            shutil.move(filestore_path_host, final_filestore_path)

            dst_count = 0
            for _, _, files in os.walk(final_filestore_path, followlinks=False):
                dst_count += len(files)

            tolerance = int(
                os.environ.get("OTCLI_FILESTORE_MISSING_TOLERANCE", "0")
            )
            expected = manifest.get("filestore_file_count", src_count)
            if (expected - dst_count) > tolerance:
                raise OdooCLIError(
                    f"Filestore restore verification failed: expected "
                    f"{expected} files, got {dst_count} in {final_filestore_path}."
                )

            logger.info(
                "Filestore restoration completed successfully (%d files).",
                dst_count,
            )
        else:
            logger.info("No filestore found in backup, skipping filestore restoration.")
    finally:
        shutil.rmtree(temp_extract_dir, ignore_errors=True)


def get_database_creation_date(db_name: str) -> str:
    """
    Get the creation date of a database.

    Args:
        db_name: Name of the database

    Returns:
        Creation date of the database
    """
    p = subprocess.Popen(
        f"PGPASSWORD=odoo psql -h localhost -U odoo -d {db_name} -t -c \"SELECT pg_database.datname, (pg_stat_file('base/'||oid ||'/PG_VERSION')).modification FROM pg_database WHERE datname = '{db_name}';\"",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output, err = p.communicate()
    if p.returncode != 0:
        logger.error(f"Error getting database creation date: {err.decode('utf-8')}")
        return ""
    return output.decode("utf-8").strip()
