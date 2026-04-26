"""Shared pytest fixtures for otcli tests.

Phase 7 removed the global ``config`` DotDict; tests now build a typed
:class:`ClientConfig` and a :class:`Settings` directly. The legacy
``fresh_config`` fixture is preserved as a thin compatibility shim that
exposes a mutable ``DotDict``-like object for tests that haven't been
migrated yet \u2014 it does NOT touch ``otcli.bootstrap`` (which is gone).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from otcli.domain.client_config import (
    ClientConfig,
    CommandHash,
    CommandShell,
    Database,
    Docker,
    Upgrade,
)
from otcli.paths import Settings


class _LegacyConfigShim(dict):
    """Tiny DotDict-like used by legacy tests via ``fresh_config``."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as err:
            raise AttributeError(name) from err

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``$HOME`` to a temporary directory for every test.

    Avoids polluting the user's home and keeps any stray
    ``Settings.from_env()`` call deterministic across tests.
    """
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('OTCLI_HOME', raising=False)
    return tmp_path


@pytest.fixture()
def fresh_config() -> _LegacyConfigShim:
    """Legacy compat fixture: a mutable dict with attribute access.

    Tests that pre-date phase 7 still expect ``config.x = y`` semantics.
    They are progressively being rewritten to use ``client``/``settings``;
    until then, this shim keeps them passing without depending on the
    deleted ``otcli.bootstrap`` module.
    """
    return _LegacyConfigShim()


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """A :class:`Settings` rooted at a per-test temp dir.

    Directories are NOT created on construction; call ``settings.ensure_dirs()``
    if you need them.
    """
    return Settings(app_data_dir=tmp_path / '.otcli_config')


@pytest.fixture()
def client_dict() -> dict:
    """A complete, valid raw dict suitable for ``ClientConfig.from_dict``."""
    return {
        'client': {'technical_name': 'acme', 'filestore_dir': '/var/lib/odoo/filestore'},
        'database': {
            'url': 'http://localhost:8069',
            'master_pwd': 's3cret',
            'db_name': 'acme',
        },
        'docker': {'db_container': 'db', 'odoo_container': 'odoo'},
        'upgrade': {
            'target': '18.0',
            'code_subscription': 'CODE',
            'environment': 'test',
            'repo_path': '/repo',
        },
        'commands': [],
    }


@pytest.fixture()
def client(client_dict: dict) -> ClientConfig:
    """A fully-populated :class:`ClientConfig` for tests."""
    return ClientConfig.from_dict(client_dict)


__all__ = [
    'ClientConfig',
    'CommandHash',
    'CommandShell',
    'Database',
    'Docker',
    'Upgrade',
    '_LegacyConfigShim',
]
