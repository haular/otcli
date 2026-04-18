import glob
import logging
import os

import typer

from odoo_task_cli.config import config, initialize_client_config
from odoo_task_cli.domain.exceptions import OdooCLIError
from odoo_task_cli.services.backup_odoo_service import backup_odoo_instance
from odoo_task_cli.services.edit_configuration_service import edit_configuration_interactive
from odoo_task_cli.services.restore_database_service import restore_odoo_database
from odoo_task_cli.services.upgrade_database_service import upgrade_database

logger = logging.getLogger(__name__)

app = typer.Typer()


@app.callback()
def main(ctx: typer.Context):
    """Odoo CLI Tool for database migration and management."""
    # Centralized client configuration initialization.
    # This runs once before any command is executed.
    if not initialize_client_config(edit_configuration_interactive):
        typer.echo('No se pudo inicializar la configuración del cliente. Saliendo.')
        raise typer.Exit(code=1)


@app.command(name='backup')
def backup_command(
    with_filestore: bool = typer.Option(True, '--filestore/--no-filestore', help='Include filestore in backup.'),
):
    """Realiza un backup de la base de datos Odoo."""
    backup_odoo_instance(with_filestore=with_filestore)
    typer.echo('Backup completado.')


@app.command(name='restore')
def restore_command():
    """Restaura una base de datos Odoo."""
    restore_odoo_database()
    typer.echo('Restauración completada.')


@app.command(name='upgrade')
def upgrade_command(
    backup_file: str = typer.Argument(..., help='Path to the backup file to upgrade.'),
):
    """Actualiza una base de datos Odoo."""
    try:
        upgraded_file = upgrade_database(backup_file)
        typer.echo(f'Base de datos actualizada. Archivo: {upgraded_file}')
    except OdooCLIError as err:
        typer.echo(f'Error durante la actualización: {err}')
        raise typer.Exit(code=1) from err


# --- Interactive-mode helpers ---------------------------------------------


def _prompt_select_backup_file(prompt_message: str) -> str | None:
    """List available ``.zip`` backups and let the user pick one.

    Returns the absolute path to the selected file, or ``None`` if there are
    no backups in ``config.client_backup_dir``.
    """
    backup_dir = config.client_backup_dir
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


def _do_interactive_backup() -> None:
    with_filestore = typer.confirm('¿Deseas incluir el filestore en el backup?', default=True)
    backup_odoo_instance(with_filestore=with_filestore)
    typer.echo('Operación de Backup completada.')


def _do_interactive_upgrade() -> None:
    selected = _prompt_select_backup_file('Select a backup file to upgrade (enter number)')
    if selected is None:
        return
    upgrade_database(backup_file=selected)
    typer.echo('Operación de Actualización completada.')


def _do_interactive_edit_config() -> None:
    try:
        edit_configuration_interactive()
    except OdooCLIError as err:
        typer.echo(f'Error al editar la configuración: {err}')


_INTERACTIVE_ACTIONS: dict[int, tuple[str, callable]] = {
    1: ('Realizar Backup', _do_interactive_backup),
    2: ('Restaurar Base de Datos', lambda: (restore_odoo_database(), typer.echo('Operación de Restauración completada.'))),
    3: ('Actualizar Base de Datos', _do_interactive_upgrade),
    4: ('Editar Configuración', _do_interactive_edit_config),
}


@app.command(name='interactive')
def interactive_command():
    """Inicia el modo interactivo para la herramienta Odoo CLI."""
    while True:
        typer.echo('\n--- Menú Principal ---')
        for key, (label, _) in _INTERACTIVE_ACTIONS.items():
            typer.echo(f'{key}. {label}')
        typer.echo('0. Salir')

        choice = typer.prompt('Selecciona una opción', type=int)

        if choice == 0:
            typer.echo('Saliendo del modo interactivo. ¡Hasta luego!')
            raise typer.Exit()

        action = _INTERACTIVE_ACTIONS.get(choice)
        if action is None:
            typer.echo('Opción no válida. Por favor, intenta de nuevo.')
            continue
        _, handler = action
        handler()
