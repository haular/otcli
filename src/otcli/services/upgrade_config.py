"""Just-in-time wizard for the Odoo upgrade-service fields.

These three fields (``upgrade.target``, ``upgrade.code_subscription``,
``upgrade.environment``) are only meaningful when the user actually
runs an upgrade, so prompting for them at client-creation time clutters
the main wizard. We instead ask just before launching the upgrade and
optionally persist the answers back to the client TOML.
"""

from __future__ import annotations

import logging

from otcli.cli import prompts, ui
from otcli.domain.client_config import (
    ClientConfig,
    Database,
    Docker,
    Odoo,
    Upgrade,
)

logger = logging.getLogger(__name__)

_ALLOWED_ENVIRONMENTS = ('test', 'production')

DESCRIPTIONS = {
    'upgrade_target': "Versión Odoo destino para la migración (ej. '18.0').",
    'code_subscription': 'Código de suscripción de Odoo para el servicio de actualización.',
    'environment': "Entorno objetivo del servicio de actualización: 'test' o 'production'.",
}


def ask_upgrade_settings(client: ClientConfig) -> ClientConfig:
    """Prompt for upgrade-related settings and return a fresh ClientConfig.

    The original ``client`` is returned unchanged when the user backs
    out (Ctrl-C); otherwise the returned ``ClientConfig`` carries the
    new ``Upgrade`` block and is otherwise identical to the input.
    """
    ui.banner(
        'Datos de actualización',
        subtitle='Necesarios para invocar el servicio upgrade.odoo.com',
    )

    ui.section('Versión destino')
    target = prompts.ask_required_text(
        'Versión Odoo destino:',
        default=client.upgrade.target,
        description=DESCRIPTIONS['upgrade_target'],
        current_value=client.upgrade.target or None,
    )

    ui.section('Suscripción')
    code_subscription = prompts.ask_required_text(
        'Código de suscripción:',
        default=client.upgrade.code_subscription,
        description=DESCRIPTIONS['code_subscription'],
        current_value=client.upgrade.code_subscription or None,
    )

    ui.section('Entorno')
    ui.hint(DESCRIPTIONS['environment'])
    environment = (
        prompts.pick_one(
            '¿Entorno?',
            list(_ALLOWED_ENVIRONMENTS),
            default=client.upgrade.environment or None,
        )
        or client.upgrade.environment
    )

    new_cfg = ClientConfig(
        technical_name=client.technical_name,
        filestore_dir=client.filestore_dir,
        database=Database(db_name=client.database.db_name),
        docker=Docker(db_container=client.docker.db_container),
        odoo=Odoo(
            install_mode=client.odoo.install_mode,
            container_name=client.odoo.container_name,
            odoo_bin_path=client.odoo.odoo_bin_path,
            odoo_conf_path=client.odoo.odoo_conf_path,
            python_executable=client.odoo.python_executable,
        ),
        upgrade=Upgrade(
            target=target,
            code_subscription=code_subscription,
            environment=environment,
        ),
    )

    ui.section('Resumen de actualización')
    ui.kv('upgrade.target', new_cfg.upgrade.target)
    ui.kv('upgrade.environment', new_cfg.upgrade.environment)
    ui.kv('upgrade.code_subscription', new_cfg.upgrade.code_subscription)
    ui.divider()

    return new_cfg
