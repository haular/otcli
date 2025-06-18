import shutil
import tomllib
from pathlib import Path
from typing import List, Dict, Any, Optional

import toml


def get_clients(clients_config_dir: str) -> List[str]:
    clients_dir_path = Path(clients_config_dir)
    if not clients_dir_path.exists():
        return []

    clients = []
    for d in clients_dir_path.iterdir():
        if d.suffix == '.toml':
            clients.append(d.stem)
    return sorted(clients)


def create_client(client_name: str, clients_config_dir: str, templates_config_dir: str) -> str:
    clients_dir_path = Path(clients_config_dir)
    templates_dir_path = Path(templates_config_dir)

    client_file_conf = clients_dir_path / f"{client_name}.toml"
    if client_file_conf.exists():
        raise ValueError(f"El cliente '{client_name}' ya existe.")

    template_path = templates_dir_path / "template.toml"
    shutil.copy(template_path, client_file_conf)
    print(f"✅ Cliente '{client_name}' creado exitosamente en: {client_file_conf}")
    return str(client_file_conf)


def load_client_config(client_name: str, clients_config_dir: str) -> Dict[str, Any]:
    clients_dir_path = Path(clients_config_dir)
    client_file_conf = clients_dir_path / f"{client_name}.toml"
    if not client_file_conf.exists():
        raise ValueError(f"El cliente '{client_name}' no existe o no es un directorio.")

    config_data = {}  # Renombrado para evitar conflicto con el objeto 'config' global
    with open(client_file_conf, 'rb') as f:
        config_data.update(tomllib.load(f))
    return config_data


def select_client(clients_config_dir: str, templates_config_dir: str) -> Optional[str]:
    clients = get_clients(clients_config_dir)

    if not clients:
        print("No se encontraron clientes configurados.")
        print("Ingresa el nombre para crear un nuevo cliente (o deja en blanco para salir):")
        client_name = input("> ").strip()
        if not client_name:
            return None

        try:
            create_client(client_name, clients_config_dir, templates_config_dir)
            return client_name
        except ValueError as e:
            print(f"Error: {e}")
            return None

    print("\nClientes disponibles:")
    for i, client in enumerate(clients, 1):
        print(f"  {i}: {client}")
    print("---")
    print("Selecciona el cliente con el que deseas trabajar, o ingresa 'N' para crear uno nuevo:")

    while True:
        choice = input("> ").strip()

        if choice.upper() == 'N':
            print("Ingresa el nombre para el nuevo cliente:")
            new_client_name = input("> ").strip()
            if not new_client_name:
                continue

            try:
                create_client(new_client_name, clients_config_dir, templates_config_dir)
                return new_client_name
            except ValueError as e:
                print(f"Error: {e}")
                continue

        try:
            index = int(choice) - 1
            if 0 <= index < len(clients):
                return clients[index]
            else:
                print(f"Por favor, ingresa un número entre 1 y {len(clients)} o 'N'.")
        except ValueError:
            print("Entrada no válida. Por favor, ingresa un número o 'N'.")


def save_client_config(client_name: str, clients_config_dir: str, config_data: Dict[str, Any]) -> None:
    """
    Guarda la configuración actualizada de un cliente en su archivo TOML.

    Args:
        client_name: El nombre del cliente.
        clients_config_dir: El directorio base donde se guardan las configuraciones de los clientes.
        config_data: El diccionario de configuración a guardar.
    """
    config_to_save = config_data.copy()

    # Excluir claves globales de la configuración del cliente para mantenerla limpia
    keys_to_remove = ['directory_path', 'clients_config_dir', 'templates_config_dir', 'client_name', 'client_backup_dir']
    for key in keys_to_remove:
        config_to_save.pop(key, None)

    client_file_conf = Path(clients_config_dir) / f"{client_name}.toml"
    with open(client_file_conf, 'w') as f:
        toml.dump(config_to_save, f)
    print(f"✅ Configuración de '{client_name}' guardada exitosamente en: {client_file_conf}")
