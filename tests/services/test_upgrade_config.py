"""Tests for the upgrade-specific configuration wizard."""

from __future__ import annotations

from unittest.mock import patch

from otcli.domain.client_config import (
    ClientConfig,
    Database,
    Docker,
    Odoo,
    Upgrade,
)
from otcli.services import upgrade_config


def _client(**overrides) -> ClientConfig:
    base = {
        'technical_name': 'acme',
        'filestore_dir': '/srv/filestore',
        'database': Database(db_name='acme'),
        'docker': Docker(db_container='db'),
        'odoo': Odoo(install_mode='source', odoo_bin_path='/x', odoo_conf_path='/y'),
        'upgrade': Upgrade(target='', code_subscription='', environment=''),
    }
    base.update(overrides)
    return ClientConfig(**base)


def test_ask_upgrade_settings_prompts_and_returns_new_config() -> None:
    client = _client()
    with (
        patch.object(upgrade_config.prompts, 'ask_required_text', side_effect=['18.0', 'M1234']),
        patch.object(upgrade_config.prompts, 'pick_one', return_value='production'),
        patch.object(upgrade_config.ui, 'banner'),
        patch.object(upgrade_config.ui, 'section'),
        patch.object(upgrade_config.ui, 'hint'),
        patch.object(upgrade_config.ui, 'kv'),
        patch.object(upgrade_config.ui, 'divider'),
    ):
        new = upgrade_config.ask_upgrade_settings(client)

    assert new.upgrade.target == '18.0'
    assert new.upgrade.code_subscription == 'M1234'
    assert new.upgrade.environment == 'production'
    # Other fields unchanged
    assert new.technical_name == client.technical_name
    assert new.docker.db_container == client.docker.db_container


def test_ask_upgrade_settings_keeps_existing_environment_when_pick_returns_none() -> None:
    client = _client(upgrade=Upgrade(target='17.0', code_subscription='X', environment='test'))
    with (
        patch.object(upgrade_config.prompts, 'ask_required_text', side_effect=['18.0', 'M1234']),
        patch.object(upgrade_config.prompts, 'pick_one', return_value=None),
        patch.object(upgrade_config.ui, 'banner'),
        patch.object(upgrade_config.ui, 'section'),
        patch.object(upgrade_config.ui, 'hint'),
        patch.object(upgrade_config.ui, 'kv'),
        patch.object(upgrade_config.ui, 'divider'),
    ):
        new = upgrade_config.ask_upgrade_settings(client)

    assert new.upgrade.environment == 'test'  # preserved
