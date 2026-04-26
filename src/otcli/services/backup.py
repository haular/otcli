"""Backup orchestration service."""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from otcli.domain.client_config import ClientConfig
from otcli.infrastructure.backup import backup_odoo
from otcli.paths import Settings

logger = logging.getLogger(__name__)


def backup_odoo_instance(
    client: ClientConfig,
    settings: Settings,
    *,
    with_filestore: bool,
) -> Path:
    """Run the full backup pipeline for ``client`` and return the archive path."""
    typer.echo(f"Iniciando proceso de backup para el cliente: '{client.technical_name}'")
    archive = backup_odoo(client, settings, with_filestore=with_filestore)
    typer.echo(f"Proceso de backup completado para el cliente: '{client.technical_name}'")
    return archive
