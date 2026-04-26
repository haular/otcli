"""Importing otcli must not create directories on disk.

Regression test for the import-time ``os.makedirs`` calls that used to
live at the top of ``otcli/bootstrap.py`` (now removed). Side-effects on
import break sandboxes, read-only containers, and tests that rely on a
clean tmp ``$HOME``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_importing_otcli_does_not_touch_home(monkeypatch, tmp_path: Path) -> None:
    fake_home = tmp_path / 'home'
    fake_home.mkdir()
    monkeypatch.setenv('HOME', str(fake_home))
    monkeypatch.delenv('OTCLI_HOME', raising=False)

    # Force a fresh import so the module-level code runs again.
    for mod in [m for m in list(sys.modules) if m.startswith('otcli')]:
        del sys.modules[mod]

    importlib.import_module('otcli')
    importlib.import_module('otcli.cli.app')
    importlib.import_module('otcli.paths')

    config_dir = fake_home / '.otcli_config'
    assert (
        not config_dir.exists()
    ), f'Importing otcli created {config_dir} \u2014 this is a regression. No I/O is allowed at import time.'
