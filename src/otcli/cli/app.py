"""Typer application entrypoint for otcli."""

from __future__ import annotations

import logging

import typer

from otcli import logging_setup
from otcli.cli import prompts, ui
from otcli.cli.context import AppContext, get_context
from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import ClientConfigError, OdooCLIError
from otcli.infrastructure.client_config_io import list_clients, load, save
from otcli.paths import Settings
from otcli.services.backup import backup_odoo_instance
from otcli.services.config_edit import edit_configuration_interactive
from otcli.services.restore import restore_odoo_database
from otcli.services.upgrade import upgrade_database
from otcli.services.upgrade_config import ask_upgrade_settings

logger = logging.getLogger(__name__)

app = typer.Typer(help='Odoo CLI Tool for database backup, restore, and upgrade.')


# --- Client selection / creation -----------------------------------------


def _select_or_create_client(settings: Settings) -> ClientConfig:
    """Interactively pick an existing client or register a new one."""
    settings.ensure_dirs()

    clients = list_clients(settings.clients_config_dir)
    if not clients:
        ui.info('No hay clientes registrados todavía. Vamos a crear el primero.')
        return _create_new_client(settings)

    selected = prompts.pick_one('Selecciona un cliente:', clients, allow_create=True)
    if selected is None:
        return _create_new_client(settings)
    return load(selected, settings.clients_config_dir)


def _create_new_client(settings: Settings) -> ClientConfig:
    """Run the interactive editor for a brand-new client and persist it."""
    cfg = edit_configuration_interactive(existing=None)
    saved = save(cfg, settings.clients_config_dir)
    ui.success(f'Configuración guardada en {saved}')
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
        ui.error(f'Error de configuración: {err}')
        raise typer.Exit(code=1) from err

    ui.info(f"Trabajando con el cliente: '{client.technical_name}'")
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
    ui.success('Backup completado.')


@app.command(name='restore')
def restore_command(ctx: typer.Context) -> None:
    """Restaura una base de datos Odoo."""
    actx = get_context(ctx)
    restore_odoo_database(actx.client, actx.settings)
    ui.success('Restauración completada.')


@app.command(name='upgrade')
def upgrade_command(
    ctx: typer.Context,
    backup_file: str = typer.Argument(..., help='Path to the backup file to upgrade.'),
) -> None:
    """Actualiza una base de datos Odoo."""
    actx = get_context(ctx)
    try:
        upgraded_file = upgrade_database(actx.client, backup_file)
        ui.success(f'Base de datos actualizada. Archivo: {upgraded_file}')
    except OdooCLIError as err:
        ui.error(f'Error durante la actualización: {err}')
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
        ui.info(f'No clients registered in {actx.settings.clients_config_dir}.')
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
        ui.error(f'Error: {err}')
        raise typer.Exit(code=1) from err
    written = save(new_cfg, actx.settings.clients_config_dir)
    ui.success(f'Configuración guardada en {written}')


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
        ui.error(f'Client {name!r} not found at {target}')
        raise typer.Exit(code=1)

    if not yes and not prompts.confirm(f'¿Borrar {target}?', default=False):
        ui.muted('Cancelado.')
        return

    target.unlink()
    ui.success(f'Borrado {target}')


@config_app.command('show')
def config_show_command(ctx: typer.Context) -> None:
    """Print the current client's configuration."""
    actx = get_context(ctx)
    cli = actx.client
    ui.section(f'Cliente: {cli.technical_name}')
    ui.kv('filestore_dir', cli.filestore_dir)
    ui.kv('database.db_name', cli.database.db_name)
    ui.kv('docker.db_container', cli.docker.db_container)
    ui.kv('odoo.install_mode', cli.odoo.install_mode)
    if cli.odoo.install_mode == 'docker':
        ui.kv('odoo.container_name', cli.odoo.container_name)
    ui.kv('odoo.odoo_bin_path', cli.odoo.odoo_bin_path or '(auto-detect)')
    if cli.odoo.install_mode != 'docker':
        ui.kv('odoo.odoo_conf_path', cli.odoo.odoo_conf_path or '(none)')
        ui.kv('odoo.python_executable', cli.odoo.python_executable or '(shebang)')
    ui.kv('upgrade.target', cli.upgrade.target or '(no configurado)')
    ui.kv('upgrade.environment', cli.upgrade.environment or '(no configurado)')
    ui.kv('upgrade.code_subscription', cli.upgrade.code_subscription or '(no configurado)')


# --- 'backups' sub-app ---------------------------------------------------

backups_app = typer.Typer(help='Inspect generated backup archives.')
app.add_typer(backups_app, name='backups')


@backups_app.command('list')
def backups_list_command(ctx: typer.Context) -> None:
    """List all .zip backups in the backups directory."""
    actx = get_context(ctx)
    backup_dir = actx.settings.backups_dir
    if not backup_dir.is_dir():
        ui.info(f'No backups directory yet: {backup_dir}.')
        return
    zips = sorted(backup_dir.glob('*.zip'))
    if not zips:
        ui.info(f'No .zip backups in {backup_dir}.')
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
        ui.info(f'No hay directorio de backups todavía: {backup_dir}.')
        return None

    zip_paths = sorted(backup_dir.glob('*.zip'))
    if not zip_paths:
        ui.info(f'No se encontraron archivos .zip en {backup_dir}.')
        return None

    name_to_path = {p.name: str(p) for p in zip_paths}
    selected = prompts.pick_one(prompt_message, list(name_to_path.keys()))
    return name_to_path.get(selected) if selected else None


def _do_interactive_backup(actx: AppContext) -> None:
    with_filestore = prompts.confirm('¿Incluir filestore en el backup?', default=True)
    backup_odoo_instance(actx.client, actx.settings, with_filestore=with_filestore)
    ui.success('Backup completado.')


def _do_interactive_upgrade(actx: AppContext) -> AppContext:
    """Prompt for the upgrade-specific settings, persist them, and run upgrade."""
    try:
        new_cfg = ask_upgrade_settings(actx.client)
    except OdooCLIError as err:
        ui.error(f'Cancelado: {err}')
        return actx
    save(new_cfg, actx.settings.clients_config_dir)
    ui.success('Datos de actualización guardados.')

    selected = _prompt_select_backup_file(actx.settings, 'Selecciona un backup para actualizar:')
    if selected is None:
        return AppContext(settings=actx.settings, client=new_cfg)
    try:
        upgrade_database(new_cfg, backup_file=selected)
        ui.success('Operación de actualización completada.')
    except OdooCLIError as err:
        ui.error(f'Error durante la actualización: {err}')
    return AppContext(settings=actx.settings, client=new_cfg)


def _do_interactive_edit_config(actx: AppContext) -> AppContext:
    """Run the interactive editor on the current client and persist the result.

    Returns a fresh :class:`AppContext` carrying the newly-saved client
    so the caller can replace its reference and keep operating on the
    updated configuration.
    """
    try:
        new_cfg = edit_configuration_interactive(existing=actx.client)
    except OdooCLIError as err:
        ui.error(f'Error al editar la configuración: {err}')
        return actx
    save(new_cfg, actx.settings.clients_config_dir)
    ui.success('Configuración guardada.')
    return AppContext(settings=actx.settings, client=new_cfg)


# --- Interactive menu -----------------------------------------------------

# Menu choices kept as constants so tests can reference them by symbol.
_MENU_BACKUP = 'Realizar Backup'
_MENU_RESTORE = 'Restaurar Base de Datos'
_MENU_UPGRADE = 'Actualizar Base de Datos'
_MENU_EDIT = 'Editar Configuración'
_MENU_EXIT = 'Salir'

_MENU_CHOICES = (_MENU_BACKUP, _MENU_RESTORE, _MENU_UPGRADE, _MENU_EDIT, _MENU_EXIT)


@app.command(name='interactive')
def interactive_command(ctx: typer.Context) -> None:
    """Inicia el modo interactivo para la herramienta Odoo CLI."""
    actx = get_context(ctx)
    ui.banner('Odoo CLI Tool', subtitle=f'Cliente activo: {actx.client.technical_name}')

    while True:
        try:
            choice = prompts.pick_one('¿Qué quieres hacer?', list(_MENU_CHOICES))
        except OdooCLIError:
            ui.muted('Saliendo del modo interactivo.')
            return

        if choice == _MENU_EXIT or choice is None:
            ui.muted('Saliendo del modo interactivo. ¡Hasta luego!')
            return
        if choice == _MENU_BACKUP:
            _do_interactive_backup(actx)
        elif choice == _MENU_RESTORE:
            restore_odoo_database(actx.client, actx.settings)
            ui.success('Operación de restauración completada.')
        elif choice == _MENU_UPGRADE:
            actx = _do_interactive_upgrade(actx)
        elif choice == _MENU_EDIT:
            actx = _do_interactive_edit_config(actx)
