"""Shared pytest fixtures and isolation for otcli tests.

The package has import-time side effects (creates directories under the user's
home) and a global mutable ``config`` singleton. We isolate those per-test by
redirecting ``HOME`` to a temporary directory and by resetting the ``config``
object before each test.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ~/.otcli_config to a temporary directory.

    Avoids polluting the user's home during tests and ensures config.py's
    module-level ``os.makedirs`` writes into tmp.
    """
    monkeypatch.setenv('HOME', str(tmp_path))
    return tmp_path


@pytest.fixture()
def fresh_config(monkeypatch: pytest.MonkeyPatch):
    """Provide a freshly-initialised ``config`` DotDict without touching the
    user's filesystem beyond ``tmp_path``.

    Tests that need to set ``config.db_name`` etc. should use this fixture and
    mutate the returned object.
    """
    # Import lazily so the autouse ``_isolated_home`` takes effect first.
    from otcli.config import config

    # Snapshot and restore.
    original = dict(config)
    try:
        yield config
    finally:
        config.clear()
        config.update(original)
