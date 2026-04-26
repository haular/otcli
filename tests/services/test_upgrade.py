"""The upgrade pipeline must not change the calling process's working directory.

Earlier versions called ``os.chdir(config.directory_path)`` from
``services/backup.setup_working_directory`` (a global side-effect) so that
the upstream upgrade script — which writes ``upgraded.zip`` next to the
current working directory — landed somewhere predictable. That coupled the
backup pipeline to a hidden global ``cwd`` mutation. This test pins the
new contract: ``run_upgrade`` manages its own temporary directory and
leaves the caller's ``cwd`` untouched, even if the upstream script raises.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from otcli.domain.exceptions import OdooCLIError
from otcli.infrastructure.upgrade import run_upgrade


def _empty_zip(path: Path) -> None:
    # Minimal valid empty zip (just an EOCD record).
    path.write_bytes(b'PK\x05\x06' + b'\x00' * 18)


def _fake_run_factory():
    """Return a fake ``run`` that materialises the artefacts the upstream
    script would normally produce.

    First call (curl): touch ``odoo-upgrade.py`` in the current cwd.
    Second call (python3 odoo-upgrade.py): touch ``upgraded.zip`` in cwd.
    """
    state = {'calls': 0}

    def _fake_run(argv, *args, **kwargs):
        state['calls'] += 1
        if state['calls'] == 1:
            Path('odoo-upgrade.py').write_text('# stub\n')
        else:
            Path('upgraded.zip').write_bytes(b'PK\x05\x06' + b'\x00' * 18)
        return

    return _fake_run, state


def test_run_upgrade_does_not_change_cwd(tmp_path: Path, fresh_config) -> None:
    fresh_config.code_subscription = 'CODE'
    fresh_config.upgrade_target = '18.0'
    fresh_config.environment = 'test'
    fresh_config.directory_path = str(tmp_path / 'unused')

    backup = tmp_path / 'backup.zip'
    _empty_zip(backup)
    cwd_before = os.getcwd()

    fake_run, _ = _fake_run_factory()
    with patch('otcli.infrastructure.upgrade.run', side_effect=fake_run):
        result = run_upgrade(str(backup))

    assert os.getcwd() == cwd_before, 'run_upgrade must not chdir the caller.'
    # Result is moved next to the input backup.
    assert Path(result) == tmp_path / 'upgraded.zip'
    assert (tmp_path / 'upgraded.zip').is_file()


def test_run_upgrade_restores_cwd_on_failure(tmp_path: Path, fresh_config) -> None:
    fresh_config.code_subscription = 'CODE'
    fresh_config.upgrade_target = '18.0'
    fresh_config.environment = 'test'

    backup = tmp_path / 'backup.zip'
    _empty_zip(backup)
    cwd_before = os.getcwd()

    def _boom(*args, **kwargs):
        raise RuntimeError('upstream blew up')

    with patch('otcli.infrastructure.upgrade.run', side_effect=_boom), pytest.raises(RuntimeError):
        run_upgrade(str(backup))

    assert os.getcwd() == cwd_before, 'cwd must be restored even on failure.'


def test_run_upgrade_rejects_missing_backup(tmp_path: Path, fresh_config) -> None:
    fresh_config.code_subscription = 'CODE'
    fresh_config.upgrade_target = '18.0'
    fresh_config.environment = 'test'

    with pytest.raises(OdooCLIError, match='Backup file not found'):
        run_upgrade(str(tmp_path / 'nope.zip'))
