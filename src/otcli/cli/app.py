"""Typer application entrypoint for otcli."""

from __future__ import annotations

import logging

import typer

from otcli import logging_setup
from otcli.cli import prompts
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
    if not clients:
        typer.echo('No registered clients found. Starting new client setup...')
        return _create_new_client(settings)

    selected = prompts.pick_one('Select a client', clients, allow_create=True)
    if selected is None:
        return _create_new_client(settings)
    return load(selected, settings.clients_config_dir)


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


# --- 'config' sub-app -----------------------------------------------------

config_app = typer.Typer(help='Manage client configurations.')
app.add_typer(config_app, name='config')


@config_app.command('list')
def config_list_command(ctx: typer.Context) -> None:
    """List registered clients."""
    actx = get_context(ctx)
    names = list_clients(actx.settings.clients_config_dir)
    if not names:
        typer.echo(f'No clients registered in {actx.settings.clients_config_dir}.')
        return
    for name in names:
        marker = ' (current)' if name == actx.client.technical_name else ''
        typer.echo(f'- {name}{marker}')


@config_app.command('edit')
def config_edit_command(ctx: typer.Context) -> None:
    """Edit the current client's configuration interactively."""
    actx = get_context(ctx)
    try:
        new_cfg = edit_configuration_interactive(existing=actx.client)
    except OdooCLIError as err:
        typer.echo(f'Error: {err}', err=True)
        raise typer.Exit(code=1) from err
    written = save(new_cfg, actx.settings.clients_config_dir)
    typer.echo(f'Configuration saved to {written}')


@config_app.command('delete')
def config_delete_command(
    ctx: typer.Context,
    name: str = typer.Argument(..., help='Client name to delete.'),
    yes: bool = typer.Option(False, '--yes', '-y', help='Skip confirmation.'),
) -> None:
    """Delete a client configuration TOML."""
    actx = get_context(ctx)
    target = actx.settings.clients_config_dir / f'{name}.toml'
    if not target.is_file():
        typer.echo(f'Client {name!r} not found at {target}', err=True)
        raise typer.Exit(code=1)

    if not yes and not prompts.confirm(f'Delete {target}?', default=False):
        typer.echo('Aborted.')
        return

    target.unlink()
    typer.echo(f'Deleted {target}')


@config_app.command('show')
def config_show_command(ctx: typer.Context) -> None:
    """Print the current client's configuration."""
    actx = get_context(ctx)
    typer.echo(f'Client: {actx.client.technical_name}')
    typer.echo(f'  filestore_dir       : {actx.client.filestore_dir}')
    typer.echo(f'  database.url        : {actx.client.database.url}')
    typer.echo(f'  database.db_name    : {actx.client.database.db_name}')
    typer.echo(f'  docker.db_container : {actx.client.docker.db_container}')
    typer.echo(f'  docker.odoo_container: {actx.client.docker.odoo_container}')
    typer.echo(f'  upgrade.target      : {actx.client.upgrade.target}')
    typer.echo(f'  upgrade.environment : {actx.client.upgrade.environment}')
    typer.echo(f'  upgrade.repo_path   : {actx.client.upgrade.repo_path}')
    typer.echo(f'  commands            : {len(actx.client.commands)} configured')


# --- 'backups' sub-app ---------------------------------------------------

backups_app = typer.Typer(help='Inspect generated backup archives.')
app.add_typer(backups_app, name='backups')


@backups_app.command('list')
def backups_list_command(ctx: typer.Context) -> None:
    """List all .zip backups in the backups directory."""
    actx = get_context(ctx)
    backup_dir = actx.settings.backups_dir
    if not backup_dir.is_dir():
        typer.echo(f'No backups directory yet: {backup_dir}.')
        return
    zips = sorted(backup_dir.glob('*.zip'))
    if not zips:
        typer.echo(f'No .zip backups in {backup_dir}.')
        return
    for p in zips:
        size_mb = p.stat().st_size / (1024 * 1024)
        typer.echo(f'{p.name}\t{size_mb:.1f} MB')


@backups_app.command('path')
def backups_path_command(ctx: typer.Context) -> None:
    """Print the absolute path of the backups directory."""
    actx = get_context(ctx)
    typer.echo(actx.settings.backups_dir)


# --- Interactive-mode helpers ---------------------------------------------


def _prompt_select_backup_file(settings: Settings, prompt_message: str) -> str | None:
    """List available ``.zip`` backups and let the user pick one."""
    backup_dir = settings.backups_dir
    if not backup_dir.is_dir():
        typer.echo(f'No backups directory yet: {backup_dir}.')
        return None

    zip_paths = sorted(backup_dir.glob('*.zip'))
    if not zip_paths:
        typer.echo(f'No .zip backup files found in {backup_dir}.')
        return None

    name_to_path = {p.name: str(p) for p in zip_paths}
    selected = prompts.pick_one(prompt_message, list(name_to_path.keys()))
    return name_to_path.get(selected) if selected else None


def _do_interactive_backup(actx: AppContext) -> None:
    with_filestore = prompts.confirm('Include filestore in the backup?', default=True)
    backup_odoo_instance(actx.client, actx.settings, with_filestore=with_filestore)
    typer.echo('Backup operation completed.')


def _do_interactive_upgrade(actx: AppContext) -> None:
    selected = _prompt_select_backup_file(actx.settings, 'Select a backup file to upgrade')
    if selected is None:
        return
    upgrade_database(actx.client, backup_file=selected)
    typer.echo('Upgrade operation completed.')


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
