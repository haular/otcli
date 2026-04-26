"""Interactive client configuration editor.

This module presents prompts to the user, validates input, and returns a
typed :class:`ClientConfig`. The CLI layer is responsible for actually
persisting the result via
:func:`otcli.infrastructure.client_config_io.save`.

The wizard branches on the chosen ``odoo.install_mode``: for ``docker``
it asks for the Odoo container; for ``native`` and ``source`` it skips
the container question and asks for an absolute path to ``odoo-bin``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

import typer

from otcli.cli import prompts
from otcli.domain.client_config import (
    ClientConfig,
    Database,
    Docker,
    Odoo,
    Upgrade,
)
from otcli.services._prompts import _handle_docker_container_selection, _prompt_for_value

logger = logging.getLogger(__name__)

# --- Field descriptions shown to the user --------------------------------
DESCRIPTIONS = {
    'environment': "Entorno objetivo para el servicio de actualización de Odoo: 'test' o 'production'.",
    'upgrade_target': "Define el objetivo para la actualización de la base de datos (ej. '18.0').",
    'filestore_dir': (
        "Ruta base para los filestores. Se le anexará '/filestore/' y el nombre técnico del cliente "
        '(ej. si la ruta es /mnt/odoo, el resultado será /mnt/odoo/filestore/mi_cliente).'
    ),
    'code_subscription': 'Código de suscripción de Odoo para el servicio de actualización.',
    'db_container_name': 'Nombre del contenedor Docker de la base de datos (PostgreSQL).',
    'odoo_install_mode': (
        "Cómo está instalado Odoo: 'docker' (en un contenedor), 'native' "
        "(instalado en el host, ej. paquete Debian), o 'source' (clonado de "
        'GitHub en una ruta del host).'
    ),
    'odoo_container_name': 'Nombre del contenedor Docker de la instancia de Odoo.',
    'odoo_bin_path_docker': (
        "Ruta absoluta a 'odoo-bin' DENTRO del contenedor de Odoo. Déjalo vacío "
        'para auto-detectar (probará which/odoo-bin, /usr/bin/odoo-bin, '
        '/mnt/odoo/odoo-bin, /opt/odoo/odoo-bin).'
    ),
    'odoo_bin_path_native': (
        "Ruta absoluta a 'odoo-bin' EN EL HOST. Déjalo vacío para auto-detectar "
        '(probará `which odoo-bin` y luego /usr/bin/odoo-bin).'
    ),
    'odoo_bin_path_source': (
        "Ruta absoluta a 'odoo-bin' DENTRO DEL CLON DE ODOO en el host (ej. /home/user/odoo/odoo-bin). Obligatorio."
    ),
    'odoo_conf_path_native': (
        'Ruta absoluta a un archivo odoo.conf en el host. Opcional: el paquete '
        'Debian de Odoo lee /etc/odoo/odoo.conf por defecto. Si tu instalación '
        'lo necesita expl\u00edcitamente, indícalo aquí; se pasará a odoo-bin con -c.'
    ),
    'odoo_conf_path_source': (
        'Ruta absoluta a un archivo odoo.conf en el host (ej. '
        '/home/user/projects/cliente/odoo.conf). Obligatorio: odoo-bin '
        'necesita -c para conocer la conexión a Postgres y los addons-path.'
    ),
    'python_executable_native': (
        'Ruta absoluta al int\u00e9rprete Python a usar para invocar odoo-bin. '
        'Opcional: si lo dejas vac\u00edo se respeta el shebang de odoo-bin '
        '(que normalmente apunta al python del sistema). Configura este '
        'campo si Odoo tiene sus dependencias instaladas en un venv '
        '(ej. /path/to/venv/bin/python3).'
    ),
    'python_executable_source': (
        'Ruta absoluta al int\u00e9rprete Python a usar para invocar odoo-bin. '
        'En instalaciones source, el shebang de odoo-bin apunta al python '
        'del sistema, que normalmente NO tiene las dependencias de Odoo '
        '(babel, psycopg2, etc.) y la neutralizaci\u00f3n falla con ImportError. '
        'Configura este campo apuntando al python del venv donde corres '
        'Odoo (ej. /home/user/developed/venvs/18.0/.venv/bin/python3).'
    ),
    'technical_client_name': (
        'Nombre técnico del cliente. Se utilizará como nombre de la base de datos y para el directorio del filestore.'
    ),
}

_ALLOWED_ENVIRONMENTS = ('test', 'production')
_ALLOWED_INSTALL_MODES = ('docker', 'native', 'source')


def _existing_value(existing: ClientConfig | None, key: str) -> str:
    """Return the current value of ``key`` from ``existing``, or empty string."""
    if existing is None:
        return ''
    return _CONFIG_KEY_GETTERS.get(key, lambda _c: '')(existing)


_CONFIG_KEY_GETTERS: dict[str, Callable[[ClientConfig], str]] = {
    'technical_client_name': lambda c: c.technical_name,
    'environment': lambda c: c.upgrade.environment,
    'filestore_dir': lambda c: c.filestore_dir,
    'upgrade_target': lambda c: c.upgrade.target,
    'code_subscription': lambda c: c.upgrade.code_subscription,
    'db_container_name': lambda c: c.docker.db_container,
    'odoo_install_mode': lambda c: c.odoo.install_mode,
    'odoo_container_name': lambda c: c.odoo.container_name,
    'odoo_bin_path': lambda c: c.odoo.odoo_bin_path,
    'odoo_conf_path': lambda c: c.odoo.odoo_conf_path,
    'python_executable': lambda c: c.odoo.python_executable,
}


def edit_configuration_interactive(existing: ClientConfig | None = None) -> ClientConfig:
    """Walk the user through every configurable field and return a ClientConfig.

    Pass ``existing`` to pre-fill prompts when editing a known client.
    Pass ``None`` (the default) when registering a brand-new client.
    """
    typer.echo('\n--- Iniciando Edición de Configuración ---')

    # --- Common fields (all modes share these) -----------------------
    environment = _ask_environment(existing)
    technical_client_name = _ask_text('technical_client_name', existing)
    upgrade_target = _ask_text('upgrade_target', existing)
    filestore_dir = _ask_filestore_dir(existing)
    code_subscription = _ask_text('code_subscription', existing)
    db_container_name = _ask_db_container(existing)

    # --- Odoo install mode (drives the next branch) ------------------
    install_mode = _ask_install_mode(existing)

    odoo_container_name = ''
    odoo_bin_path = ''
    odoo_conf_path = ''
    python_executable = ''
    if install_mode == 'docker':
        odoo_container_name = _ask_odoo_container(existing)
        odoo_bin_path = _ask_odoo_bin_path(existing, mode='docker')
    elif install_mode == 'native':
        odoo_bin_path = _ask_odoo_bin_path(existing, mode='native')
        odoo_conf_path = _ask_odoo_conf_path(existing, mode='native')
        python_executable = _ask_python_executable(existing, mode='native')
    elif install_mode == 'source':
        odoo_bin_path = _ask_odoo_bin_path(existing, mode='source')
        odoo_conf_path = _ask_odoo_conf_path(existing, mode='source')
        python_executable = _ask_python_executable(existing, mode='source')

    cfg = ClientConfig(
        technical_name=technical_client_name,
        filestore_dir=filestore_dir,
        database=Database(db_name=technical_client_name),
        docker=Docker(db_container=db_container_name),
        odoo=Odoo(
            install_mode=install_mode,
            container_name=odoo_container_name,
            odoo_bin_path=odoo_bin_path,
            odoo_conf_path=odoo_conf_path,
            python_executable=python_executable,
        ),
        upgrade=Upgrade(
            target=upgrade_target,
            code_subscription=code_subscription,
            environment=environment,
        ),
    )

    typer.echo('\n--- Edición de Configuración Completada ---')
    return cfg


# --- Prompt helpers -------------------------------------------------------


def _ask_environment(existing: ClientConfig | None) -> str:
    current = _existing_value(existing, 'environment')
    choice = prompts.pick_one(DESCRIPTIONS['environment'], list(_ALLOWED_ENVIRONMENTS))
    return choice if choice else current


def _ask_install_mode(existing: ClientConfig | None) -> str:
    current = _existing_value(existing, 'odoo_install_mode')
    choice = prompts.pick_one(DESCRIPTIONS['odoo_install_mode'], list(_ALLOWED_INSTALL_MODES))
    return choice if choice else current


def _ask_text(key: str, existing: ClientConfig | None) -> str:
    return _prompt_for_value(key, _existing_value(existing, key), DESCRIPTIONS[key])


def _ask_filestore_dir(existing: ClientConfig | None) -> str:
    current = _existing_value(existing, 'filestore_dir')
    raw = _prompt_for_value('filestore_dir', current, DESCRIPTIONS['filestore_dir'])
    if existing is None and not raw.rstrip('/').endswith('filestore'):
        raw = os.path.join(raw, 'filestore')
    return raw


def _ask_db_container(existing: ClientConfig | None) -> str:
    current = _existing_value(existing, 'db_container_name')
    container = _handle_docker_container_selection(
        current,
        DESCRIPTIONS['db_container_name'],
        role='database (PostgreSQL)',
    )
    if container is None:
        typer.echo('Selección de contenedor Docker cancelada; se conserva el valor actual.')
        return current
    return container


def _ask_odoo_container(existing: ClientConfig | None) -> str:
    current = _existing_value(existing, 'odoo_container_name')
    container = _handle_docker_container_selection(
        current,
        DESCRIPTIONS['odoo_container_name'],
        role='Odoo',
    )
    if container is None:
        typer.echo('Selección de contenedor Docker cancelada; se conserva el valor actual.')
        return current
    return container


def _ask_odoo_bin_path(existing: ClientConfig | None, *, mode: str) -> str:
    """Ask for ``odoo-bin`` path with mode-specific guidance.

    For ``docker`` and ``native`` an empty answer is fine (auto-detect);
    for ``source`` we re-prompt until the user provides a non-empty
    absolute path.
    """
    current = _existing_value(existing, 'odoo_bin_path')
    description = DESCRIPTIONS[f'odoo_bin_path_{mode}']

    if mode == 'source':
        while True:
            value = _prompt_for_value('odoo_bin_path', current, description)
            if value:
                return value
            typer.echo("La ruta es obligatoria cuando install_mode='source'.")

    return _prompt_for_value('odoo_bin_path', current, description)


def _ask_odoo_conf_path(existing: ClientConfig | None, *, mode: str) -> str:
    """Ask for the ``odoo.conf`` path. Optional in native, mandatory in source."""
    current = _existing_value(existing, 'odoo_conf_path')
    description = DESCRIPTIONS[f'odoo_conf_path_{mode}']

    if mode == 'source':
        while True:
            value = _prompt_for_value('odoo_conf_path', current, description)
            if value:
                return value
            typer.echo("La ruta del odoo.conf es obligatoria cuando install_mode='source'.")

    return _prompt_for_value('odoo_conf_path', current, description)


def _ask_python_executable(existing: ClientConfig | None, *, mode: str) -> str:
    """Ask for the Python interpreter to invoke odoo-bin with. Always optional."""
    current = _existing_value(existing, 'python_executable')
    description = DESCRIPTIONS[f'python_executable_{mode}']
    return _prompt_for_value('python_executable', current, description)
