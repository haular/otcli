"""Interactive client configuration editor.

This module presents prompts to the user, validates input, and returns a
typed :class:`ClientConfig`. The CLI layer is responsible for actually
persisting the result via
:func:`otcli.infrastructure.client_config_io.save`.
"""

from __future__ import annotations

import logging
import os

import typer

from otcli.cli import prompts
from otcli.domain.client_config import (
    ClientConfig,
    CommandHash,
    CommandShell,
    Database,
    Docker,
    Upgrade,
)
from otcli.services._prompts import _handle_docker_container_selection, _prompt_for_value

logger = logging.getLogger(__name__)

# --- Field descriptions shown to the user --------------------------------
DESCRIPTIONS = {
    'environment': "Entorno objetivo para el servicio de actualización de Odoo: 'test' o 'production'.",
    'url': 'URL utilizada para restaurar la base de datos a través de una petición CURL (ej. http://localhost:8069).',
    'upgrade_target': "Define el objetivo para la actualización de la base de datos (ej. '18.0').",
    'master_pwd': 'Contraseña maestra de Odoo para operaciones de base de datos.',
    'filestore_dir': (
        "Ruta base para los filestores. Se le anexará '/filestore/' y el nombre técnico del cliente "
        '(ej. si la ruta es /mnt/odoo, el resultado será /mnt/odoo/filestore/mi_cliente).'
    ),
    'code_subscription': 'Código de suscripción de Odoo para el servicio de actualización.',
    'db_container_name': 'Nombre del contenedor Docker de la base de datos (PostgreSQL).',
    'odoo_container_name': 'Nombre del contenedor Docker de la instancia de Odoo.',
    'repo_path': 'Ruta absoluta al repositorio Git del proyecto.',
    'technical_client_name': (
        'Nombre técnico del cliente. Se utilizará como nombre de la base de datos y para el directorio del filestore.'
    ),
}

CONFIG_FIELDS_ORDER = [
    'environment',
    'technical_client_name',
    'url',
    'upgrade_target',
    'master_pwd',
    'filestore_dir',
    'code_subscription',
    'db_container_name',
    'odoo_container_name',
    'repo_path',
]

_ALLOWED_ENVIRONMENTS = ('test', 'production')


def _existing_value(existing: ClientConfig | None, key: str) -> str:
    """Return the current value of ``key`` from ``existing``, or empty string."""
    if existing is None:
        return ''
    return _CONFIG_KEY_GETTERS.get(key, lambda _c: '')(existing)


_CONFIG_KEY_GETTERS: dict[str, callable] = {
    'technical_client_name': lambda c: c.technical_name,
    'environment': lambda c: c.upgrade.environment,
    'url': lambda c: c.database.url,
    'master_pwd': lambda c: c.database.master_pwd,
    'filestore_dir': lambda c: c.filestore_dir,
    'upgrade_target': lambda c: c.upgrade.target,
    'code_subscription': lambda c: c.upgrade.code_subscription,
    'db_container_name': lambda c: c.docker.db_container,
    'odoo_container_name': lambda c: c.docker.odoo_container,
    'repo_path': lambda c: c.upgrade.repo_path,
}


def edit_configuration_interactive(existing: ClientConfig | None = None) -> ClientConfig:
    """Walk the user through every configurable field and return a ClientConfig.

    Pass ``existing`` to pre-fill prompts when editing a known client.
    Pass ``None`` (the default) when registering a brand-new client.
    """
    typer.echo('\n--- Iniciando Edición de Configuración ---')

    answers: dict[str, str] = {}

    for key in CONFIG_FIELDS_ORDER:
        current_value = _existing_value(existing, key)
        description = DESCRIPTIONS[key]

        if key == 'environment':
            choice = prompts.pick_one(description, list(_ALLOWED_ENVIRONMENTS))
            answers[key] = choice if choice else current_value
        elif key == 'master_pwd':
            answers[key] = prompts.ask_secret(f'{description}\n{key}:') or current_value
        elif key == 'db_container_name':
            db_container_name = _handle_docker_container_selection(current_value, description)
            if db_container_name is None:
                typer.echo('Selección de contenedor Docker cancelada.')
                continue
            answers[key] = db_container_name
        elif key == 'filestore_dir':
            base_filestore_path = _prompt_for_value(key, current_value, description)
            answers[key] = os.path.join(base_filestore_path, 'filestore')
        else:
            answers[key] = _prompt_for_value(key, current_value, description)

    # Existing commands are preserved when re-editing.
    commands: list[CommandHash | CommandShell] = list(existing.commands) if existing else []
    commands = _manage_commands_section(commands)

    cfg = ClientConfig(
        technical_name=answers['technical_client_name'],
        filestore_dir=answers['filestore_dir'],
        database=Database(
            url=answers.get('url', ''),
            master_pwd=answers.get('master_pwd', ''),
            db_name=answers['technical_client_name'],
        ),
        docker=Docker(
            db_container=answers.get('db_container_name', ''),
            odoo_container=answers.get('odoo_container_name', ''),
        ),
        upgrade=Upgrade(
            target=answers.get('upgrade_target', ''),
            code_subscription=answers.get('code_subscription', ''),
            environment=answers.get('environment', ''),
            repo_path=answers.get('repo_path', ''),
        ),
        commands=tuple(commands),
    )

    typer.echo('\n--- Edición de Configuración Completada ---')
    return cfg


# --- Commands sub-menu ---------------------------------------------------


def _manage_commands_section(
    commands: list[CommandHash | CommandShell],
) -> list[CommandHash | CommandShell]:
    typer.echo('\n--- Gestionando Comandos ---')
    while True:
        typer.echo('\n--- Menú de Comandos ---')
        typer.echo('1. Listar Comandos')
        typer.echo('2. Añadir Comando')
        typer.echo('3. Eliminar Comando')
        typer.echo('0. Volver a Edición de Configuración')

        choice = typer.prompt('Selecciona una opción', type=int)

        if choice == 1:
            _list_commands(commands)
        elif choice == 2:
            _add_command(commands)
        elif choice == 3:
            _delete_command(commands)
        elif choice == 0:
            return commands
        else:
            typer.echo('Opción no válida. Por favor, intenta de nuevo.')


def _list_commands(commands: list[CommandHash | CommandShell]) -> None:
    typer.echo('\n--- Comandos Configurados ---')
    if not commands:
        typer.echo('No hay comandos configurados.')
        return
    for i, cmd in enumerate(commands, 1):
        if isinstance(cmd, CommandHash):
            typer.echo(f'{i}. Tipo: Git Hash, Valor: {cmd.value}')
        else:
            typer.echo(f'{i}. Tipo: Shell Command, Valor: {" ".join(cmd.value)}')


def _add_command(commands: list[CommandHash | CommandShell]) -> None:
    typer.echo('\n--- Añadir Nuevo Comando ---')
    typer.echo('Selecciona el tipo de comando:')
    typer.echo('1. Git Hash')
    typer.echo('2. Shell Command')
    command_type_choice = typer.prompt('Tipo de comando', type=int)

    if command_type_choice == 1:
        value = typer.prompt('Introduce el hash de Git')
        commands.append(CommandHash(value=value))
    elif command_type_choice == 2:
        command_str = typer.prompt("Introduce el comando de shell (ej. 'docker ps -a')")
        commands.append(CommandShell(value=command_str.split()))
    else:
        typer.echo('Tipo de comando no válido.')
        return
    typer.echo('Comando añadido exitosamente.')


def _delete_command(commands: list[CommandHash | CommandShell]) -> None:
    typer.echo('\n--- Eliminar Comando ---')
    if not commands:
        typer.echo('No hay comandos para eliminar.')
        return
    _list_commands(commands)
    try:
        index_to_delete = typer.prompt('Introduce el número del comando a eliminar', type=int) - 1
        if 0 <= index_to_delete < len(commands):
            deleted = commands.pop(index_to_delete)
            typer.echo(f'Comando eliminado: {deleted}')
        else:
            typer.echo('Número de comando no válido.')
    except ValueError:
        typer.echo('Entrada no válida. Por favor, introduce un número.')
