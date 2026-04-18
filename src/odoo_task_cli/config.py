""" "
Configuration settings for the Odoo migration tool.
Loads configuration from TOML files.
"""

import os
from pathlib import Path

import typer

from odoo_task_cli.domain.models import DotDict
from odoo_task_cli.infrastructure.config_manager import load_client_config, select_client

# Determine the base directory of the project
DIRECTORY_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup user-specific configuration directory in the home folder
user_home_dir = Path.home()
app_data_dir = user_home_dir / '.odoo_task_cli_config'
clients_config_dir = app_data_dir / 'clientes'
backups_dir = app_data_dir / 'backups'

# Create user-specific directories if they don't exist
os.makedirs(clients_config_dir, exist_ok=True)
os.makedirs(backups_dir, exist_ok=True)

# Create the config object
config = DotDict()

# Set dynamic and absolute paths in the config
config.directory_path = DIRECTORY_PATH
config.clients_config_dir = str(clients_config_dir)
config.client_backup_dir = str(backups_dir)

from collections.abc import Callable


def initialize_client_config(create_new_config_callback: Callable[[], None]) -> bool:
    """
    Inicializa la configuración del cliente al inicio de la aplicación.

    Esta función debe ser llamada una sola vez para seleccionar el cliente
    y cargar su configuración.

    Returns:
        True si un cliente fue seleccionado y su configuración cargada, False en caso contrario.
    """
    selected_client = select_client(config.clients_config_dir)
    if not selected_client:
        typer.echo('No se encontró ningún cliente configurado. Iniciando la creación de una nueva configuración...')
        create_new_config_callback()
        # Después de crear la configuración, intentamos seleccionar de nuevo
        selected_client = select_client(config.clients_config_dir)
        if not selected_client:
            typer.echo('No se pudo crear o seleccionar un cliente. Saliendo.')
            return False
    typer.echo(f"\nTrabajando con el cliente: '{selected_client}'")
    try:
        client_config = load_client_config(selected_client, config.clients_config_dir)
        if not client_config:
            print('La configuración del cliente está vacía.')
        config.client_name = selected_client
        config.update(client_config)
        return True
    except ValueError as e:
        print(f'Error al cargar la configuración: {e}')
        return False
