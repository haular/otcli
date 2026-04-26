"""Defence-in-depth tests for ``load_client_config``.

Even after the save-side whitelist (Task 1.1) prevents new TOMLs from being
written with runtime keys, existing TOMLs on the user's disk still contain
those legacy keys. ``load_client_config`` must strip them so they cannot be
re-injected into the runtime DotDict via ``config.update(client_config)``.
"""

from __future__ import annotations

from pathlib import Path

import toml

from otcli.infrastructure.client_config import load_client_config


def test_load_strips_legacy_runtime_keys(tmp_path: Path) -> None:
    legacy = {
        # Legacy runtime keys we must drop on load.
        'client_name': 'old',
        'clients_config_dir': '/old/path',
        'client_backup_dir': '/old/backups',
        'directory_path': '/old/dir',
        # Real client-owned keys.
        'technical_client_name': 'acme',
        'db_name': 'acme',
        'master_pwd': 's3cret',
    }
    (tmp_path / 'acme.toml').write_text(toml.dumps(legacy))

    loaded = load_client_config('acme', str(tmp_path))

    assert 'client_name' not in loaded
    assert 'clients_config_dir' not in loaded
    assert 'client_backup_dir' not in loaded
    assert 'directory_path' not in loaded

    assert loaded['technical_client_name'] == 'acme'
    assert loaded['db_name'] == 'acme'
    assert loaded['master_pwd'] == 's3cret'
