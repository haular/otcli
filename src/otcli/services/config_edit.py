"""Interactive client configuration editor.

This module presents prompts to the user, validates input, and returns a
typed :class:`ClientConfig`. The CLI layer is responsible for actually
persisting the result via
:func:`otcli.infrastructure.client_config_io.save`.
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
    'odoo_container_name': 'Nombre del contenedor Docker de la instancia de Odoo.',
    'odoo_bin_path': (
        "Ruta absoluta a 'odoo-bin' dentro del contenedor de Odoo. Déjalo vacío para "
        'auto-detectar (probará which/odoo-bin, /usr/bin/odoo-bin, /mnt/odoo/odoo-bin, '
        '/opt/odoo/odoo-bin). Solo necesitas configurarlo si la auto-detección falla.'
    ),
    'technical_client_name': (
        'Nombre técnico del cliente. Se utilizará como nombre de la base de datos y para el directorio del filestore.'
    ),
}

CONFIG_FIELDS_ORDER = [
    'environment',
    'technical_client_name',
    'upgrade_target',
    'filestore_dir',
    'code_subscription',
    'db_container_name',
    'odoo_container_name',
    'odoo_bin_path',
]

_ALLOWED_ENVIRONMENTS = ('test', 'production')


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
    'odoo_container_name': lambda c: c.docker.odoo_container,
    'odoo_bin_path': lambda c: c.docker.odoo_bin_path,
}


def edit_configuration_interactive(existing: ClientConfig | None = None) -> ClientConfig:
    """Walk the user through every configurable field and return a ClientConfig.

    Pass ``existing`` to pre-fill prompts when editing a known client.
    Pass ``None`` (the default) when registering a brand-new client.
    """
    typer.echo('\n--- Iniciando Edición de Configuración ---')

    answers: dict[str, str] = {}

    for key in CONFIG_FIELDS_ORDER:
        current_value = _existing_value(existing, key)
        description = DESCRIPTIONS[key]

        if key == 'environment':
            choice = prompts.pick_one(description, list(_ALLOWED_ENVIRONMENTS))
            answers[key] = choice if choice else current_value
        elif key in ('db_container_name', 'odoo_container_name'):
            container = _handle_docker_container_selection(current_value, description)
            if container is None:
                typer.echo('Selección de contenedor Docker cancelada.')
                continue
            answers[key] = container
        elif key == 'filestore_dir':
            # The persisted ``filestore_dir`` is the parent directory that
            # contains a per-client subdirectory (the backup/restore code
            # joins ``client.technical_name`` to it). When editing an
            # existing config we already store the post-join path; for
            # new entries we append "/filestore" to whatever the user
            # types so the wizard can stay short.
            raw = _prompt_for_value(key, current_value, description)
            if existing is None and not raw.rstrip('/').endswith('filestore'):
                # New entry: append ``/filestore`` if the user gave the
                # parent dir (e.g. /mnt/odoo -> /mnt/odoo/filestore).
                raw = os.path.join(raw, 'filestore')
            answers[key] = raw
        else:
            answers[key] = _prompt_for_value(key, current_value, description)

    cfg = ClientConfig(
        technical_name=answers['technical_client_name'],
        filestore_dir=answers['filestore_dir'],
        database=Database(db_name=answers['technical_client_name']),
        docker=Docker(
            db_container=answers.get('db_container_name', ''),
            odoo_container=answers.get('odoo_container_name', ''),
            odoo_bin_path=answers.get('odoo_bin_path', ''),
        ),
        upgrade=Upgrade(
            target=answers.get('upgrade_target', ''),
            code_subscription=answers.get('code_subscription', ''),
            environment=answers.get('environment', ''),
        ),
    )

    typer.echo('\n--- Edición de Configuración Completada ---')
    return cfg
