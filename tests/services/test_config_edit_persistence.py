"""Regression test: derived runtime paths must not leak into the client TOML.

Before this fix, ``_save_current_config`` serialised the entire runtime
``DotDict`` — including paths like ``client_backup_dir`` and the in-memory
``client_name`` — into the client's TOML file. On the next run, that TOML
was loaded back via ``config.update(client_config)`` and overwrote the
freshly-computed paths from ``bootstrap.py``, sending backups to the legacy
``~/.odoo_task_cli_config/`` tree even though the package had been renamed.

The whitelist in ``_save_current_config`` prevents that leak: only keys that
genuinely belong to the client configuration are persisted.
"""

from __future__ import annotations

from pathlib import Path

import toml

from otcli.services.config_edit import _save_current_config


def test_save_does_not_persist_runtime_paths(tmp_path: Path, fresh_config) -> None:
    fresh_config.client_name = 'acme'
    # Override the clients_config_dir to write into the temp dir.
    fresh_config.clients_config_dir = str(tmp_path)
    # These are the runtime/derived keys that must NOT leak into the TOML.
    fresh_config.client_backup_dir = '/tmp/should-not-leak'
    fresh_config.directory_path = '/tmp/also-should-not-leak'
    # Real client-owned keys.
    fresh_config.technical_client_name = 'acme'
    fresh_config.db_name = 'acme'
    fresh_config.url = 'http://x'
    fresh_config.upgrade_target = '18.0'
    fresh_config.master_pwd = 'secret'
    fresh_config.filestore_dir = '/data/filestore'
    fresh_config.code_subscription = ''
    fresh_config.db_container_name = 'db'
    fresh_config.odoo_container_name = 'odoo'
    fresh_config.repo_path = '/repo'

    _save_current_config()

    persisted = toml.load(tmp_path / 'acme.toml')
    forbidden = {'client_name', 'clients_config_dir', 'client_backup_dir', 'directory_path'}
    leaked = forbidden & set(persisted.keys())
    assert not leaked, f'Runtime keys leaked into TOML: {leaked}'

    # Real client keys must still be there.
    assert persisted['technical_client_name'] == 'acme'
    assert persisted['master_pwd'] == 'secret'
    assert persisted['db_container_name'] == 'db'
