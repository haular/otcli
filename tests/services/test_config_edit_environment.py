"""Smoke tests for the new wizard structure (post install_mode rework).

The pre-rework wizard exposed flat ``CONFIG_FIELDS_ORDER`` /
``DESCRIPTIONS`` modules; the new wizard branches on install_mode and
exposes individual ``_ask_*`` helpers. These tests pin a few invariants:
``environment`` and ``odoo_install_mode`` are described, the legacy
``linked_production_client`` and ``repo_path`` keys are gone, and every
DESCRIPTION key is non-empty (no placeholders).
"""

from __future__ import annotations

from otcli.services.config_edit import DESCRIPTIONS


def test_environment_described() -> None:
    assert DESCRIPTIONS.get('environment')


def test_install_mode_described() -> None:
    assert DESCRIPTIONS.get('odoo_install_mode')


def test_no_legacy_keys() -> None:
    forbidden = {'linked_production_client', 'repo_path', 'url', 'master_pwd'}
    assert forbidden.isdisjoint(DESCRIPTIONS.keys())


def test_descriptions_non_empty() -> None:
    for key, desc in DESCRIPTIONS.items():
        assert desc, f'description for {key!r} is empty'
