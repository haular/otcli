import os
from typing import Any

import toml
import typer

# Keys that some legacy TOMLs (pre 1.0) accidentally persisted from the
# runtime config. Strip them on load so they cannot override the freshly
# computed runtime paths via ``config.update(client_config)``.
_LEGACY_RUNTIME_KEYS: frozenset[str] = frozenset({'client_name', 'clients_config_dir', 'client_backup_dir', 'directory_path'})


def get_clients(clients_config_dir: str) -> list[str]:
    """
    Lists all available client configuration files (TOML files) in the specified directory.
    """
    clients = []
    if os.path.exists(clients_config_dir):
        for f in os.listdir(clients_config_dir):
            if f.endswith('.toml'):
                clients.append(os.path.splitext(f)[0])
    return clients


def load_client_config(client_name: str, clients_config_dir: str) -> dict[str, Any]:
    """
    Loads the configuration for a specific client from its TOML file.

    Legacy runtime keys persisted by pre-1.0 versions of the tool are
    stripped silently so they cannot override the runtime paths derived
    from the user's environment.
    """
    config_path = os.path.join(clients_config_dir, f'{client_name}.toml')
    if not os.path.exists(config_path):
        raise ValueError(f'Client configuration file not found: {config_path}')
    with open(config_path) as f:
        raw = toml.load(f)
    return {k: v for k, v in raw.items() if k not in _LEGACY_RUNTIME_KEYS}


def save_client_config(client_name: str, clients_config_dir: str, config_data: dict[str, Any]) -> None:
    """
    Saves the configuration for a specific client to its TOML file.
    """
    config_path = os.path.join(clients_config_dir, f'{client_name}.toml')
    with open(config_path, 'w') as f:
        toml.dump(config_data, f)


def select_client(clients_config_dir: str) -> str | None:
    """
    Interactively prompts the user to select a client from available configurations.
    """
    clients = get_clients(clients_config_dir)
    if not clients:
        return None

    typer.echo('\nClientes disponibles:')
    for i, client in enumerate(clients, 1):
        typer.echo(f'{i}. {client}')
    typer.echo('0. Crear nuevo cliente')

    while True:
        try:
            choice = typer.prompt("Selecciona un cliente (número o nombre) o '0' para crear uno nuevo", type=str)
            if choice == '0':
                return None  # Indica que se quiere crear un nuevo cliente
            if choice.isdigit():
                index = int(choice) - 1
                if 0 <= index < len(clients):
                    return clients[index]
                typer.echo('Número no válido. Intenta de nuevo.')
            elif choice in clients:
                return choice
            else:
                typer.echo('Nombre de cliente no encontrado. Intenta de nuevo.')
        except ValueError:
            typer.echo("Entrada no válida. Por favor, ingresa un número, el nombre del cliente o '0'.")
