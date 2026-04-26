"""Unit tests for the typed ClientConfig schema."""

from __future__ import annotations

import pytest

from otcli.domain.client_config import (
    ClientConfig,
    Database,
    Docker,
    Odoo,
    Upgrade,
)
from otcli.domain.exceptions import ClientConfigError


def _full_dict() -> dict:
    return {
        'client': {
            'technical_name': 'acme',
            'filestore_dir': '/var/lib/odoo/filestore',
        },
        'database': {'db_name': 'acme'},
        'docker': {'db_container': 'db'},
        'odoo': {
            'install_mode': 'docker',
            'container_name': 'odoo',
            'odoo_bin_path': '',
        },
        'upgrade': {
            'target': '18.0',
            'code_subscription': 'CODE',
            'environment': 'test',
        },
    }


def test_minimal_round_trip():
    raw = _full_dict()
    cfg = ClientConfig.from_dict(raw)
    assert cfg.technical_name == 'acme'
    assert cfg.database.db_name == 'acme'
    assert cfg.odoo.install_mode == 'docker'
    assert cfg.odoo.container_name == 'odoo'
    assert cfg.odoo.odoo_bin_path == ''

    round_tripped = cfg.to_dict()
    assert round_tripped['odoo']['install_mode'] == 'docker'

    cfg2 = ClientConfig.from_dict(round_tripped)
    assert cfg2 == cfg


def test_db_name_defaults_to_technical_name():
    raw = _full_dict()
    raw['database'].pop('db_name', None)
    cfg = ClientConfig.from_dict(raw)
    assert cfg.database.db_name == 'acme'


def test_database_section_is_optional():
    raw = _full_dict()
    raw.pop('database')
    cfg = ClientConfig.from_dict(raw)
    assert cfg.database.db_name == 'acme'


def test_db_name_override():
    raw = _full_dict()
    raw['database']['db_name'] = 'something_else'
    cfg = ClientConfig.from_dict(raw)
    assert cfg.database.db_name == 'something_else'


def test_missing_required_section_raises():
    raw = _full_dict()
    raw.pop('docker')
    with pytest.raises(ClientConfigError, match='docker'):
        ClientConfig.from_dict(raw)


def test_missing_odoo_section_raises():
    raw = _full_dict()
    raw.pop('odoo')
    with pytest.raises(ClientConfigError, match='odoo'):
        ClientConfig.from_dict(raw)


def test_missing_required_field_raises():
    raw = _full_dict()
    raw['client'].pop('technical_name')
    with pytest.raises(ClientConfigError, match='technical_name'):
        ClientConfig.from_dict(raw)


def test_unknown_top_level_section_rejected():
    raw = {
        'technical_client_name': 'acme',
        'db_name': 'acme',
        'master_pwd': 'p',
    }
    with pytest.raises(ClientConfigError, match='legacy'):
        ClientConfig.from_dict(raw)


def test_commands_section_now_rejected():
    raw = _full_dict()
    raw['commands'] = []
    with pytest.raises(ClientConfigError, match='legacy'):
        ClientConfig.from_dict(raw)


def test_invalid_environment_rejected():
    raw = _full_dict()
    raw['upgrade']['environment'] = 'staging'
    with pytest.raises(ClientConfigError, match='environment'):
        ClientConfig.from_dict(raw)


# --- install_mode -------------------------------------------------------


def test_install_mode_required():
    raw = _full_dict()
    raw['odoo'].pop('install_mode')
    with pytest.raises(ClientConfigError, match='install_mode is required'):
        ClientConfig.from_dict(raw)


def test_install_mode_invalid_rejected():
    raw = _full_dict()
    raw['odoo']['install_mode'] = 'kubernetes'
    with pytest.raises(ClientConfigError, match='install_mode'):
        ClientConfig.from_dict(raw)


def test_docker_mode_requires_container_name():
    raw = _full_dict()
    raw['odoo']['container_name'] = ''
    with pytest.raises(ClientConfigError, match='container_name is required'):
        ClientConfig.from_dict(raw)


def test_native_mode_does_not_need_container_name():
    raw = _full_dict()
    raw['odoo']['install_mode'] = 'native'
    raw['odoo']['container_name'] = ''
    raw['odoo']['odoo_bin_path'] = ''
    cfg = ClientConfig.from_dict(raw)
    assert cfg.odoo.install_mode == 'native'
    assert cfg.odoo.container_name == ''
    assert cfg.odoo.odoo_bin_path == ''  # auto-detect


def test_source_mode_requires_odoo_bin_path():
    raw = _full_dict()
    raw['odoo']['install_mode'] = 'source'
    raw['odoo']['container_name'] = ''
    raw['odoo']['odoo_bin_path'] = ''
    with pytest.raises(ClientConfigError, match='odoo_bin_path is required'):
        ClientConfig.from_dict(raw)


def test_source_mode_with_explicit_path():
    raw = _full_dict()
    raw['odoo']['install_mode'] = 'source'
    raw['odoo']['container_name'] = ''
    raw['odoo']['odoo_bin_path'] = '/home/user/odoo/odoo-bin'
    cfg = ClientConfig.from_dict(raw)
    assert cfg.odoo.install_mode == 'source'
    assert cfg.odoo.odoo_bin_path == '/home/user/odoo/odoo-bin'


def test_odoo_bin_path_round_trips():
    raw = _full_dict()
    raw['odoo']['odoo_bin_path'] = '/custom/odoo-bin'
    cfg = ClientConfig.from_dict(raw)
    assert cfg.odoo.odoo_bin_path == '/custom/odoo-bin'

    cfg2 = ClientConfig.from_dict(cfg.to_dict())
    assert cfg2.odoo.odoo_bin_path == '/custom/odoo-bin'


def test_constructor_helpers():
    db = Database(db_name='acme')
    docker = Docker(db_container='db')
    odoo = Odoo(install_mode='docker', container_name='odoo')
    upgrade = Upgrade(target='18.0', code_subscription='C', environment='production')
    cfg = ClientConfig(
        technical_name='acme',
        filestore_dir='/x',
        database=db,
        docker=docker,
        odoo=odoo,
        upgrade=upgrade,
    )
    assert cfg.odoo.install_mode == 'docker'
    assert cfg.odoo.odoo_bin_path == ''  # default
