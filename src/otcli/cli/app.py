"""Typer application entrypoint for otcli."""

from __future__ import annotations

import glob
import logging
import os

import typer

from otcli import logging_setup
from otcli.cli.context import AppContext, get_context
from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import ClientConfigError, OdooCLIError
from otcli.infrastructure.client_config_io import list_clients, load, save
from otcli.paths import Settings
from otcli.services.backup import backup_odoo_instance
from otcli.services.config_edit import edit_configuration_interactive
from otcli.services.restore import restore_odoo_database
from otcli.services.upgrade import upgrade_database

logger = logging.getLogger(__name__)

app = typer.Typer(help='Odoo CLI Tool for database backup, restore, and upgrade.')


# --- Client selection / creation -----------------------------------------


def _select_or_create_client(settings: Settings) -> ClientConfig:
    """Interactively pick an existing client or register a new one."""
    settings.ensure_dirs()

    clients = list_clients(settings.clients_config_dir)
    if clients:
        typer.echo('\nClientes disponibles:')
        for i, name in enumerate(clients, 1):
            typer.echo(f'{i}. {name}')
        typer.echo('0. Crear nuevo cliente')

        while True:
            choice = typer.prompt(
                "Selecciona un cliente (número o nombre) o '0' para crear uno nuevo",
                type=str,
            )
            if choice == '0':
                return _create_new_client(settings)
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(clients):
                    return load(clients[idx], settings.clients_config_dir)
                typer.echo('Número no válido. Intenta de nuevo.')
                continue
            if choice in clients:
                return load(choice, settings.clients_config_dir)
            typer.echo('Nombre de cliente no encontrado. Intenta de nuevo.')

    typer.echo('No se encontró ningún cliente configurado. Iniciando la creación de una nueva configuración...')
    return _create_new_client(settings)


def _create_new_client(settings: Settings) -> ClientConfig:
    """Run the interactive editor for a brand-new client and persist it."""
    cfg = edit_configuration_interactive(existing=None)
    saved = save(cfg, settings.clients_config_dir)
    typer.echo(f'Configuración guardada en {saved}')
    return cfg


# --- Top-level callback ---------------------------------------------------


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, '--verbose', '-v', help='Enable debug logging (very noisy).'),
    client_name: str | None = typer.Option(
        None,
        '--client',
        '-c',
        envvar='OTCLI_CLIENT',
        help='Client to operate on. Skips the interactive selection.',
    ),
) -> None:
    """Odoo CLI Tool for database migration and management."""
    logging_setup.configure(verbose=verbose)

    settings = Settings.from_env()

    try:
        if client_name:
            settings.ensure_dirs()
            client = load(client_name, settings.clients_config_dir)
        else:
            client = _select_or_create_client(settings)
    except ClientConfigError as err:
        typer.echo(f'Error de configuración: {err}', err=True)
        raise typer.Exit(code=1) from err

    typer.echo(f"\nTrabajando con el cliente: '{client.technical_name}'")
    ctx.obj = AppContext(settings=settings, client=client)


# --- Commands -------------------------------------------------------------


@app.command(name='backup')
def backup_command(
    ctx: typer.Context,
    with_filestore: bool = typer.Option(True, '--filestore/--no-filestore', help='Include filestore in backup.'),
) -> None:
    """Realiza un backup de la base de datos Odoo."""
    actx = get_context(ctx)
    backup_odoo_instance(actx.client, actx.settings, with_filestore=with_filestore)
    typer.echo('Backup completado.')


@app.command(name='restore')
def restore_command(ctx: typer.Context) -> None:
    """Restaura una base de datos Odoo."""
    actx = get_context(ctx)
    restore_odoo_database(actx.client, actx.settings)
    typer.echo('Restauración completada.')


@app.command(name='upgrade')
def upgrade_command(
    ctx: typer.Context,
    backup_file: str = typer.Argument(..., help='Path to the backup file to upgrade.'),
) -> None:
    """Actualiza una base de datos Odoo."""
    actx = get_context(ctx)
    try:
        upgraded_file = upgrade_database(actx.client, backup_file)
        typer.echo(f'Base de datos actualizada. Archivo: {upgraded_file}')
    except OdooCLIError as err:
        typer.echo(f'Error durante la actualización: {err}')
        raise typer.Exit(code=1) from err


# --- Interactive-mode helpers ---------------------------------------------


def _prompt_select_backup_file(settings: Settings, prompt_message: str) -> str | None:
    """List available ``.zip`` backups and let the user pick one."""
    backup_dir = str(settings.backups_dir)
    zip_files = sorted(glob.glob(os.path.join(backup_dir, '*.zip')))

    if not zip_files:
        typer.echo(f'No .zip backup files found in {backup_dir}.')
        return None

    typer.echo(f'Found {len(zip_files)} backup files in {backup_dir}:')
    for i, zip_file in enumerate(zip_files, 1):
        typer.echo(f'  {i}: {os.path.basename(zip_file)}')

    while True:
        try:
            choice = typer.prompt(prompt_message, type=int)
        except ValueError:
            typer.echo('Invalid input. Please enter a number.')
            continue
        index = choice - 1
        if 0 <= index < len(zip_files):
            return zip_files[index]
        typer.echo('Invalid selection. Please enter a valid number.')


def _do_interactive_backup(actx: AppContext) -> None:
    with_filestore = typer.confirm('¿Deseas incluir el filestore en el backup?', default=True)
    backup_odoo_instance(actx.client, actx.settings, with_filestore=with_filestore)
    typer.echo('Operación de Backup completada.')


def _do_interactive_upgrade(actx: AppContext) -> None:
    selected = _prompt_select_backup_file(actx.settings, 'Select a backup file to upgrade (enter number)')
    if selected is None:
        return
    upgrade_database(actx.client, backup_file=selected)
    typer.echo('Operación de Actualización completada.')


def _do_interactive_edit_config(actx: AppContext) -> AppContext:
    """Run the interactive editor on the current client and persist the result.

    Returns a fresh :class:`AppContext` carrying the newly-saved client
    so the caller can replace its reference and keep operating on the
    updated configuration.
    """
    try:
        new_cfg = edit_configuration_interactive(existing=actx.client)
    except OdooCLIError as err:
        typer.echo(f'Error al editar la configuración: {err}')
        return actx
    save(new_cfg, actx.settings.clients_config_dir)
    typer.echo('Configuración guardada.')
    return AppContext(settings=actx.settings, client=new_cfg)


@app.command(name='interactive')
def interactive_command(ctx: typer.Context) -> None:
    """Inicia el modo interactivo para la herramienta Odoo CLI."""
    actx = get_context(ctx)

    while True:
        typer.echo('\n--- Menú Principal ---')
        typer.echo('1. Realizar Backup')
        typer.echo('2. Restaurar Base de Datos')
        typer.echo('3. Actualizar Base de Datos')
        typer.echo('4. Editar Configuración')
        typer.echo('0. Salir')

        choice = typer.prompt('Selecciona una opción', type=int)

        if choice == 0:
            typer.echo('Saliendo del modo interactivo. ¡Hasta luego!')
            raise typer.Exit()
        if choice == 1:
            _do_interactive_backup(actx)
        elif choice == 2:
            restore_odoo_database(actx.client, actx.settings)
            typer.echo('Operación de Restauración completada.')
        elif choice == 3:
            _do_interactive_upgrade(actx)
        elif choice == 4:
            actx = _do_interactive_edit_config(actx)
        else:
            typer.echo('Opción no válida. Por favor, intenta de nuevo.')
