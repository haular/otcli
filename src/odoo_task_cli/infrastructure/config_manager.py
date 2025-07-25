import os
from typing import Dict, Any, Optional, List

import toml
import typer


def get_clients(clients_config_dir: str) -> List[str]:
    """
    Lists all available client configuration files (TOML files) in the specified directory.
    """
    clients = []
    if os.path.exists(clients_config_dir):
        for f in os.listdir(clients_config_dir):
            if f.endswith(".toml"):
                clients.append(os.path.splitext(f)[0])
    return clients


def load_client_config(client_name: str, clients_config_dir: str) -> Dict[str, Any]:
    """
    Loads the configuration for a specific client from its TOML file.
    """
    config_path = os.path.join(clients_config_dir, f"{client_name}.toml")
    if not os.path.exists(config_path):
        raise ValueError(f"Client configuration file not found: {config_path}")
    with open(config_path, "r") as f:
        return toml.load(f)


def save_client_config(client_name: str, clients_config_dir: str, config_data: Dict[str, Any]) -> None:
    """
    Saves the configuration for a specific client to its TOML file.
    """
    config_path = os.path.join(clients_config_dir, f"{client_name}.toml")
    with open(config_path, "w") as f:
        toml.dump(config_data, f)


def select_client(clients_config_dir: str) -> Optional[str]:
    """
    Interactively prompts the user to select a client from available configurations.
    """
    clients = get_clients(clients_config_dir)
    if not clients:
        return None

    typer.echo("\nClientes disponibles:")
    for i, client in enumerate(clients, 1):
        typer.echo(f"{i}. {client}")
    typer.echo("0. Crear nuevo cliente")

    while True:
        try:
            choice = typer.prompt("Selecciona un cliente (número o nombre) o '0' para crear uno nuevo", type=str)
            if choice == "0":
                return None  # Indica que se quiere crear un nuevo cliente
            elif choice.isdigit():
                index = int(choice) - 1
                if 0 <= index < len(clients):
                    return clients[index]
                else:
                    typer.echo("Número no válido. Intenta de nuevo.")
            elif choice in clients:
                return choice
            else:
                typer.echo("Nombre de cliente no encontrado. Intenta de nuevo.")
        except ValueError:
            typer.echo("Entrada no válida. Por favor, ingresa un número, el nombre del cliente o '0'.")
