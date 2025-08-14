import logging
import os

import typer

from odoo_task_cli.config import config
from odoo_task_cli.infrastructure.config_manager import save_client_config
from odoo_task_cli.services.edit_configuration_helpers import (_prompt_for_value, _handle_docker_container_selection)

logger = logging.getLogger(__name__)

# --- Descripciones de los campos de configuración ---
DESCRIPTIONS = {
    "url": "URL utilizada para restaurar la base de datos a través de una petición CURL (ej. http://localhost:8069).",
    "upgrade_target": "Define el objetivo para la actualización de la base de datos (ej. '18.0').",
    "master_pwd": "Contraseña maestra de Odoo para operaciones de base de datos.",
    "filestore_dir": "Ruta base para los filestores. Se le anexará '/filestore/' y el nombre técnico del cliente (ej. si la ruta es /mnt/odoo, el resultado será /mnt/odoo/filestore/mi_cliente).",
    "code_subscription": "Código de suscripción de Odoo para el servicio de actualización.",
    "db_container_name": "Nombre del contenedor Docker de la base de datos (PostgreSQL).",
    "odoo_container_name": "Nombre del contenedor Docker de la instancia de Odoo.",
    "repo_path": "Ruta absoluta al repositorio Git del proyecto.",
    "technical_client_name": "Nombre técnico del cliente. Se utilizará como nombre de la base de datos y para el directorio del filestore.",
    "linked_production_client": "Nombre del cliente de producción vinculado (solo para entornos de prueba).",
    "remote_backup_enabled": "Habilita backups remotos via SSH (true/false).",
    "remote_user_host": "Usuario y host SSH para backups remotos (ej. usuario@servidor.com).",
    "remote_path": "Ruta remota donde guardar los backups (ej. /home/usuario/backups/)."
}

# --- Orden de los campos para el flujo secuencial ---
CONFIG_FIELDS_ORDER = [
    "technical_client_name",
    "remote_backup_enabled",
    "remote_user_host",
    "remote_path",
    "url",
    "upgrade_target",
    "master_pwd",
    "filestore_dir",
    "code_subscription",
    "db_container_name",
    "odoo_container_name",
    "repo_path",
]


def edit_configuration_interactive() -> None:
    typer.echo("\n--- Iniciando Edición de Configuración ---")

    for key in CONFIG_FIELDS_ORDER:
        current_value = config.get(key, "")
        description = DESCRIPTIONS[key]

        if key == "technical_client_name":
            new_value = _prompt_for_value(key, current_value, description)
            config.technical_client_name = new_value
            config.db_name = new_value  # Asignar db_name automáticamente
            config.client_name = new_value
        elif key == "remote_backup_enabled":
            current_bool_value = config.get(key, False)
            new_value = typer.confirm(f"{description} ¿Habilitar?", default=current_bool_value)
            config[key] = new_value
        elif key in ["remote_user_host", "remote_path"]:
            if config.get("remote_backup_enabled", False):
                new_value = _prompt_for_value(key, current_value, description)
                config[key] = new_value
            else:
                typer.echo(f"Saltando {key} (backups remotos deshabilitados)")
                config[key] = ""  # Valor vacío para campos no aplicables
        elif key in ["url", "upgrade_target", "master_pwd", "filestore_dir", "code_subscription", "db_container_name", "odoo_container_name", "repo_path"]:
            if config.get("remote_backup_enabled", False):
                typer.echo(f"Saltando {key} (cliente remoto, no necesario)")
                config[key] = ""  # Valor vacío para cliente remoto
            elif key == "db_container_name":
                db_container_name = _handle_docker_container_selection(current_value, description)
                if db_container_name is not None:
                    config.db_container_name = db_container_name
                else:
                    typer.echo("Selección de contenedor Docker cancelada.")
                    continue
            elif key == "filestore_dir":
                base_filestore_path = _prompt_for_value(key, current_value, description)
                config.filestore_dir = os.path.join(base_filestore_path, 'filestore')
            else:
                new_value = _prompt_for_value(key, current_value, description)
                config[key] = new_value
        else:
            new_value = _prompt_for_value(key, current_value, description)
            config[key] = new_value

    # After all individual fields, offer command management
    manage_commands_section()

    _save_current_config()
    typer.echo("\n--- Edición de Configuración Completada y Guardada ---")


def manage_commands_section() -> None:
    typer.echo("\n--- Gestionando Comandos ---")
    while True:
        typer.echo("\n--- Menú de Comandos ---")
        typer.echo("1. Listar Comandos")
        typer.echo("2. Añadir Comando")
        typer.echo("3. Eliminar Comando")
        typer.echo("0. Volver a Edición de Configuración")

        choice = typer.prompt("Selecciona una opción", type=int)

        if choice == 1:
            list_commands()
        elif choice == 2:
            add_command()
        elif choice == 3:
            delete_command()
        elif choice == 0:
            return
        else:
            typer.echo("Opción no válida. Por favor, intenta de nuevo.")


def list_commands() -> None:
    typer.echo("\n--- Comandos Configurados ---")
    if not config.get("commands"):
        typer.echo("No hay comandos configurados.")
        return

    for i, cmd_obj in enumerate(config.commands, 1):
        if "hash" in cmd_obj:
            typer.echo(f"{i}. Tipo: Git Hash, Valor: {cmd_obj['hash']}")
        elif "command" in cmd_obj:
            typer.echo(f"{i}. Tipo: Shell Command, Valor: {' '.join(cmd_obj['command'])}")


def add_command() -> None:
    typer.echo("\n--- Añadir Nuevo Comando ---")
    typer.echo("Selecciona el tipo de comando:")
    typer.echo("1. Git Hash")
    typer.echo("2. Shell Command")
    command_type_choice = typer.prompt("Tipo de comando", type=int)

    new_command_obj = {}
    if command_type_choice == 1:
        new_command_obj["hash"] = typer.prompt("Introduce el hash de Git")
    elif command_type_choice == 2:
        command_str = typer.prompt("Introduce el comando de shell (ej. 'docker ps -a')")
        new_command_obj["command"] = command_str.split()
    else:
        typer.echo("Tipo de comando no válido.")
        return

    if not config.get("commands"):
        config.commands = []
    config.commands.append(new_command_obj)
    _save_current_config()
    typer.echo("Comando añadido exitosamente.")


def delete_command() -> None:
    typer.echo("\n--- Eliminar Comando ---")
    if not config.get("commands"):
        typer.echo("No hay comandos para eliminar.")
        return

    list_commands()  # Mostrar comandos para que el usuario elija
    try:
        index_to_delete = typer.prompt("Introduce el número del comando a eliminar", type=int) - 1
        if 0 <= index_to_delete < len(config.commands):
            deleted_command = config.commands.pop(index_to_delete)
            _save_current_config()
            typer.echo(f"Comando eliminado: {deleted_command}")
        else:
            typer.echo("Número de comando no válido.")
    except ValueError:
        typer.echo("Entrada no válida. Por favor, introduce un número.")


def _save_current_config() -> None:
    current_client_name = config.client_name
    if not current_client_name:
        typer.echo("Error: No se pudo determinar el cliente actual para guardar la configuración.")
        return

    config_to_save = config.to_dict()
    save_client_config(current_client_name, config.clients_config_dir, config_to_save)
    typer.echo("Configuración guardada.")
