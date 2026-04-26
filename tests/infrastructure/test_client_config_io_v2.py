"""Tests for the new ClientConfig TOML I/O layer.

This is the v2 IO module used by phase 7 onwards. It uses stdlib
``tomllib`` for reads and ``tomli-w`` for writes; legacy flat TOMLs are
rejected with ``ClientConfigError``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import ClientConfigError
from otcli.infrastructure.client_config_io import list_clients, load, save


def _full_dict() -> dict:
    return {
        'client': {'technical_name': 'acme', 'filestore_dir': '/x'},
        'database': {'db_name': 'acme'},
        'docker': {'db_container': 'db'},
        'odoo': {
            'install_mode': 'docker',
            'container_name': 'odoo',
            'odoo_bin_path': '',
            'odoo_conf_path': '',
            'python_executable': '',
        },
        'upgrade': {
            'target': '18.0',
            'code_subscription': 'CODE',
            'environment': 'test',
        },
    }


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    cfg = ClientConfig.from_dict(_full_dict())

    written = save(cfg, tmp_path)

    assert written == tmp_path / 'acme.toml'
    assert written.is_file()

    loaded = load('acme', tmp_path)
    assert loaded == cfg


def test_list_clients(tmp_path: Path) -> None:
    cfg1 = ClientConfig.from_dict(_full_dict())
    cfg2_raw = _full_dict()
    cfg2_raw['client']['technical_name'] = 'beta'
    cfg2 = ClientConfig.from_dict(cfg2_raw)
    save(cfg1, tmp_path)
    save(cfg2, tmp_path)

    assert list_clients(tmp_path) == ['acme', 'beta']


def test_list_clients_empty_dir(tmp_path: Path) -> None:
    assert list_clients(tmp_path) == []


def test_list_clients_nonexistent_dir(tmp_path: Path) -> None:
    assert list_clients(tmp_path / 'does_not_exist') == []


def test_load_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ClientConfigError, match='not found'):
        load('ghost', tmp_path)


def test_load_legacy_flat_raises(tmp_path: Path) -> None:
    """Pre-1.0 TOMLs (flat keys like technical_client_name) must fail loudly."""
    legacy = 'technical_client_name = "old"\ndb_name = "old"\nmaster_pwd = "p"\n'
    (tmp_path / 'old.toml').write_text(legacy)
    with pytest.raises(ClientConfigError, match='legacy'):
        load('old', tmp_path)


def test_save_creates_dir_if_missing(tmp_path: Path) -> None:
    target = tmp_path / 'sub' / 'nested'
    cfg = ClientConfig.from_dict(_full_dict())
    save(cfg, target)
    assert (target / 'acme.toml').is_file()
