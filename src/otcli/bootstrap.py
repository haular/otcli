"""Configuration bootstrap for the Odoo migration tool.

This module is a transitional shim: it still exposes the legacy
``config`` :class:`DotDict` that the rest of the codebase reads, but it
no longer performs any I/O at import time. Filesystem directories are
created lazily by :func:`initialize_client_config`, which is invoked by
the Typer callback on every CLI invocation.

Phase 7 of the 1.0.0 plan replaces this module entirely with explicit
``Settings`` and ``ClientConfig`` arguments threaded through the service
layer.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import typer

from otcli.domain.dotdict import DotDict
from otcli.infrastructure.client_config import load_client_config, select_client
from otcli.paths import Settings

# Determine the base directory of the project (used by the upgrade flow).
DIRECTORY_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Resolve filesystem layout from the environment. No I/O happens here.
_settings = Settings.from_env()

# Public, mutable runtime config. Populated lazily during CLI startup.
config = DotDict()
config.directory_path = DIRECTORY_PATH
config.clients_config_dir = str(_settings.clients_config_dir)
config.client_backup_dir = str(_settings.backups_dir)


def initialize_client_config(create_new_config_callback: Callable[[], None]) -> bool:
    """Initialise the client config at CLI startup.

    Creates the data directories on disk (``~/.otcli_config/...``) the
    first time it runs, then prompts the user to select or create a
    client. Returns ``True`` on success, ``False`` if the user cancelled
    or no client could be loaded.
    """
    # Lazy directory creation: the very first call from a Typer command
    # creates the layout, but importing the package never does.
    _settings.ensure_dirs()

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
            typer.echo('La configuración del cliente está vacía.')
        config.client_name = selected_client
        config.update(client_config)
        return True
    except ValueError as err:
        typer.echo(f'Error al cargar la configuración: {err}')
        return False
