"""Unit tests for the typed ClientConfig schema."""

from __future__ import annotations

import pytest

from otcli.domain.client_config import (
    ClientConfig,
    CommandHash,
    CommandShell,
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
        'database': {
            'url': 'http://localhost:8069',
            'master_pwd': 's3cret',
        },
        'docker': {
            'db_container': 'db',
            'odoo_container': 'odoo',
        },
        'upgrade': {
            'target': '18.0',
            'code_subscription': 'CODE',
            'environment': 'test',
            'repo_path': '/repo',
        },
        'commands': [
            {'type': 'hash', 'value': 'abc123'},
            {'type': 'shell', 'value': ['docker', 'ps', '-a']},
        ],
    }


def test_minimal_round_trip():
    raw = _full_dict()
    cfg = ClientConfig.from_dict(raw)
    assert cfg.technical_name == 'acme'
    assert cfg.database.master_pwd == 's3cret'
    assert cfg.database.db_name == 'acme'  # defaulted

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


def test_db_name_override():
    raw = _full_dict()
    raw['database']['db_name'] = 'something_else'
    cfg = ClientConfig.from_dict(raw)
    assert cfg.database.db_name == 'something_else'


def test_missing_required_section_raises():
    raw = _full_dict()
    raw.pop('database')
    with pytest.raises(ClientConfigError, match='database'):
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


def test_invalid_environment_rejected():
    raw = _full_dict()
    raw['upgrade']['environment'] = 'staging'
    with pytest.raises(ClientConfigError, match='environment'):
        ClientConfig.from_dict(raw)


def test_unknown_command_type_rejected():
    raw = _full_dict()
    raw['commands'].append({'type': 'magic', 'value': 'x'})
    with pytest.raises(ClientConfigError, match='magic'):
        ClientConfig.from_dict(raw)


def test_commands_round_trip():
    raw = _full_dict()
    cfg = ClientConfig.from_dict(raw)
    assert len(cfg.commands) == 2
    assert isinstance(cfg.commands[0], CommandHash)
    assert cfg.commands[0].value == 'abc123'
    assert isinstance(cfg.commands[1], CommandShell)
    assert cfg.commands[1].value == ['docker', 'ps', '-a']


def test_optional_sections_default_empty():
    """Missing 'commands' is fine; everything else is required."""
    raw = _full_dict()
    raw.pop('commands')
    cfg = ClientConfig.from_dict(raw)
    assert cfg.commands == ()


def test_constructor_helpers():
    db = Database(url='http://x', master_pwd='p', db_name='acme')
    docker = Docker(db_container='db', odoo_container='odoo')
    upgrade = Upgrade(target='18.0', code_subscription='C', environment='production', repo_path='/r')
    cfg = ClientConfig(
        technical_name='acme',
        filestore_dir='/x',
        database=db,
        docker=docker,
        upgrade=upgrade,
    )
    assert cfg.database.url == 'http://x'
