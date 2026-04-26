"""Unit tests for the typed ClientConfig schema."""

from __future__ import annotations

import pytest

from otcli.domain.client_config import (
    ClientConfig,
    Database,
    Docker,
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
        'docker': {
            'db_container': 'db',
            'odoo_container': 'odoo',
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
    assert cfg.docker.odoo_bin_path == ''

    round_tripped = cfg.to_dict()
    assert round_tripped['client']['technical_name'] == 'acme'
    assert round_tripped['database']['db_name'] == 'acme'

    cfg2 = ClientConfig.from_dict(round_tripped)
    assert cfg2 == cfg


def test_db_name_defaults_to_technical_name():
    raw = _full_dict()
    raw['database'].pop('db_name', None)
    cfg = ClientConfig.from_dict(raw)
    assert cfg.database.db_name == 'acme'


def test_database_section_is_optional():
    """Removing the [database] section entirely is fine; db_name defaults."""
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


def test_missing_required_field_raises():
    raw = _full_dict()
    raw['client'].pop('technical_name')
    with pytest.raises(ClientConfigError, match='technical_name'):
        ClientConfig.from_dict(raw)


def test_unknown_top_level_section_rejected():
    """Pre-1.0 flat configs (top-level keys instead of sections) must fail loudly."""
    raw = {
        'technical_client_name': 'acme',
        'db_name': 'acme',
        'master_pwd': 'p',
    }
    with pytest.raises(ClientConfigError, match='legacy'):
        ClientConfig.from_dict(raw)


def test_commands_section_now_rejected():
    """The deprecated [[commands]] section is no longer accepted."""
    raw = _full_dict()
    raw['commands'] = []
    with pytest.raises(ClientConfigError, match='legacy'):
        ClientConfig.from_dict(raw)


def test_invalid_environment_rejected():
    raw = _full_dict()
    raw['upgrade']['environment'] = 'staging'
    with pytest.raises(ClientConfigError, match='environment'):
        ClientConfig.from_dict(raw)


def test_odoo_bin_path_round_trips():
    raw = _full_dict()
    raw['docker']['odoo_bin_path'] = '/custom/odoo-bin'
    cfg = ClientConfig.from_dict(raw)
    assert cfg.docker.odoo_bin_path == '/custom/odoo-bin'

    cfg2 = ClientConfig.from_dict(cfg.to_dict())
    assert cfg2.docker.odoo_bin_path == '/custom/odoo-bin'


def test_constructor_helpers():
    db = Database(db_name='acme')
    docker = Docker(db_container='db', odoo_container='odoo')
    upgrade = Upgrade(target='18.0', code_subscription='C', environment='production')
    cfg = ClientConfig(
        technical_name='acme',
        filestore_dir='/x',
        database=db,
        docker=docker,
        upgrade=upgrade,
    )
    assert cfg.docker.odoo_bin_path == ''  # default
    assert cfg.upgrade.environment == 'production'
