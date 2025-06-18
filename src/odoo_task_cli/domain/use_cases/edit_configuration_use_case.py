import logging
import os

import typer
from odoo_task_cli.app_config import config
from odoo_task_cli.config.client_manager import save_client_config
from odoo_task_cli.infrastructure.docker_client import list_running_containers, list_databases_in_container

logger = logging.getLogger(__name__)

# --- Descripciones de los campos de configuración ---
DESCRIPTIONS = {
    "url": "URL utilizada para restaurar la base de datos a través de una petición CURL (ej. http://localhost:8069).",
    "upgrade_target": "Define el objetivo para la actualización de la base de datos (ej. '18.0').",
    "master_pwd": "Contraseña maestra de Odoo para operaciones de base de datos.",
    "filestore_dir": "Ruta absoluta al directorio del filestore de Odoo. Se anexará el nombre técnico del cliente (ej. /mnt/filestore/mi_cliente).",
    "code_subscription": "Código de suscripción de Odoo para el servicio de actualización.",
    "db_container_name": "Nombre del contenedor Docker de la base de datos (PostgreSQL).",
    "odoo_container_name": "Nombre del contenedor Docker de la instancia de Odoo.",
    "repo_path": "Ruta absoluta al repositorio Git del proyecto.",
    "environment": "Indica si el entorno de la base de datos es 'test' o 'production'.",
    "technical_client_name": "Nombre técnico del cliente. Se utilizará como nombre de la base de datos y para el directorio del filestore."
}

# --- Orden de los campos para el flujo secuencial ---
CONFIG_FIELDS_ORDER = [
    "environment",
    "technical_client_name",
    "url",
    "upgrade_target",
    "master_pwd",
    "filestore_dir",
    "code_subscription",
    "db_container_name",
    "odoo_container_name",
    "repo_path",
]


def _prompt_for_value(key: str, current_value: str, description: str, prompt_message: str = None) -> str:
    typer.echo(f"\nDescripción: {description}")

    if prompt_message is None:
        prompt_message = f"Ingrese el valor para '{key}'"

    if current_value:
        typer.echo(f"El valor actual para '{key}' es: '{current_value}'")
        if not typer.confirm("¿Desea reemplazarlo?", default=False):
            return current_value  # Mantener el valor existente si el usuario no quiere reemplazarlo

    new_value = typer.prompt(prompt_message, default=current_value if current_value else "")
    return new_value


def edit_configuration_interactive() -> None:
    typer.echo("\n--- Iniciando Edición de Configuración ---")

    for key in CONFIG_FIELDS_ORDER:
        current_value = config.get(key, "")
        description = DESCRIPTIONS[key]

        if key == "environment":
            typer.echo(f"\nDescripción: {description}")
            options = ["test", "production"]
            current_env = config.get("environment", "test")
            typer.echo(f"El valor actual para 'environment' es: '{current_env}'")
            choice = typer.prompt(f"Seleccione el entorno ({options[0]}/{options[1]})", default=current_env, type=str)
            while choice.lower() not in options:
                typer.echo("Opción no válida. Por favor, elija 'test' o 'production'.")
                choice = typer.prompt(f"Seleccione el entorno ({options[0]}/{options[1]})", default=current_env, type=str)
            config.environment = choice.lower()
        elif key == "technical_client_name":
            new_value = _prompt_for_value(key, current_value, description)
            config.technical_client_name = new_value
            config.db_name = new_value  # Asignar db_name automáticamente
        elif key == "db_container_name":
            db_container_name = _handle_docker_container_selection(current_value, description)
            if db_container_name is not None:
                config.db_container_name = db_container_name
            else:
                typer.echo("Selección de contenedor Docker cancelada.")
                continue  # Skip to next field if selection was cancelled
        elif key == "filestore_dir":
            example_path = f"/mnt/filestore/{{config.technical_client_name}}" if config.get(
                "technical_client_name") else "/mnt/filestore/ejemplo_cliente"
            prompt_message = f"Ruta base del filestore de Odoo (ej. /mnt/filestore/). El nombre técnico del cliente se anexará automáticamente."
            base_filestore_path = _prompt_for_value(key, current_value, description, prompt_message=prompt_message)
            if base_filestore_path and config.get("technical_client_name"):
                config.filestore_dir = os.path.join(base_filestore_path, config.technical_client_name)
            else:
                config.filestore_dir = base_filestore_path  # If no technical name, use base path directly
        else:
            new_value = _prompt_for_value(key, current_value, description)
            config[key] = new_value

    # After all individual fields, offer command management
    manage_commands_section()

    _save_current_config()
    typer.echo("\n--- Edición de Configuración Completada y Guardada ---")


def _handle_docker_container_selection(current_value: str, description: str) -> str | None:
    typer.echo(f"\nDescripción: {description}")

    db_container_name = None
    while True:
        running_containers = list_running_containers()

        if not running_containers:
            typer.echo("No se encontraron contenedores Docker en ejecución.")
            db_container_name = typer.prompt(
                "Introduce el nombre del contenedor de la base de datos manualmente (o 'q' para cancelar)",
                default=current_value)
            if db_container_name.lower() == 'q':
                return None
            break
        else:
            typer.echo("\nContenedores Docker en ejecución:")
            for i, container_name in enumerate(running_containers, 1):
                typer.echo(f"{i}. {container_name}")

            container_choice = typer.prompt(
                "Selecciona el número del contenedor de la base de datos o introduce el nombre (o 'q' para cancelar)",
                type=str, default=current_value)
            if container_choice.lower() == 'q':
                return None

            if container_choice.isdigit():
                index = int(container_choice) - 1
                if 0 <= index < len(running_containers):
                    db_container_name = running_containers[index]
                    break
                else:
                    typer.echo("Número de contenedor no válido. Se usará el valor ingresado.")
                    db_container_name = container_choice  # Use the typed value if index is invalid
            else:
                db_container_name = container_choice
                break
    return db_container_name


def _handle_docker_db_selection(container_name: str, current_value: str, description: str) -> str | None:
    # This function is no longer directly called in the main loop for db_name
    # as db_name is now derived from technical_client_name.
    # However, it might still be useful if we decide to re-introduce manual db_name selection.
    typer.echo(f"\nDescripción: {description}")

    db_name = None
    databases = list_databases_in_container(container_name)

    if not databases:
        typer.echo(f"El contenedor '{container_name}' no posee bases de datos Odoo creadas o accesibles.")
        db_name = typer.prompt("Introduce el nombre de la base de datos manualmente (o 'q' para cancelar)",
                               default=current_value)
        if db_name.lower() == 'q':
            return None
    else:
        typer.echo(f"\nBases de datos encontradas en '{container_name}':")
        for i, db in enumerate(databases, 1):
            typer.echo(f"{i}. {db}")

        db_choice = typer.prompt("Selecciona el número de la base de datos o introduce el nombre (o 'q' para cancelar)",
                                 type=str, default=current_value)
        if db_choice.lower() == 'q':
            return None

        if db_choice.isdigit():
            index = int(db_choice) - 1
            if 0 <= index < len(databases):
                db_name = databases[index]
            else:
                typer.echo("Número de base de datos no válido. Se usará el valor ingresado.")
                db_name = db_choice  # Use the typed value if index is invalid
        else:
            db_name = db_choice
    return db_name


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
