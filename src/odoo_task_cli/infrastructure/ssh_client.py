"""
Functions for remote SSH operations.
"""
import logging
import subprocess

import typer

from odoo_task_cli.config import config
from odoo_task_cli.domain.exceptions import OdooCLIError

logger = logging.getLogger(__name__)


def execute_remote_command(command: str) -> None:
    """
    Executes a command on the remote server via SSH.
    """
    remote_user_host = config.remote_user_host
    
    if not remote_user_host:
        raise OdooCLIError("Remote user host not configured.")
    
    ssh_command = [
        "ssh",
        remote_user_host,
        command
    ]
    
    logger.info(f"Executing remote command: {' '.join(ssh_command)}")
    
    try:
        result = subprocess.run(
            ssh_command,
            check=True,
            capture_output=True,
            text=True
        )
        
        if result.stdout:
            typer.echo(f"Remote output: {result.stdout}")
            
    except subprocess.CalledProcessError as e:
        error_msg = f"SSH command failed: {e.stderr if e.stderr else str(e)}"
        logger.error(error_msg)
        raise OdooCLIError(error_msg)
    except FileNotFoundError:
        error_msg = "SSH command not found. Please ensure SSH is installed."
        logger.error(error_msg)
        raise OdooCLIError(error_msg)


def backup_remote_database(with_filestore: bool) -> None:
    """
    Performs a database backup on the remote server.
    """
    remote_path = config.remote_path
    db_name = config.db_name
    
    if not remote_path:
        raise OdooCLIError("Remote path not configured.")
    
    import datetime
    today = datetime.datetime.now().strftime("%d_%m_%Y")
    backup_name = f"{db_name}_{today}"
    
    typer.echo("Nota: Asegúrate de tener las claves SSH configuradas para conectar sin contraseña.")
    
    # Create backup directory if it doesn't exist
    mkdir_command = f"mkdir -p {remote_path}"
    execute_remote_command(mkdir_command)
    
    # Backup database command - this assumes pg_dump is available on remote server
    backup_command = f"pg_dump -U odoo --no-owner -d {db_name} | gzip > {remote_path}/{backup_name}.sql.gz"
    
    typer.echo(f"Iniciando backup remoto de la base de datos {db_name}...")
    execute_remote_command(backup_command)
    
    if with_filestore:
        typer.echo("Nota: El backup de filestore remoto debe ser configurado manualmente en el servidor.")
        
    typer.echo(f"Backup remoto completado: {remote_path}/{backup_name}.sql.gz")