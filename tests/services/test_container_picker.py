"""Tests for the Docker container picker used by the wizard.

The picker is shared between db_container_name and odoo_container_name;
it lists running containers via questionary and gracefully degrades to a
manual prompt when no containers are detected.
"""

from __future__ import annotations

from unittest.mock import patch

from otcli.services import _prompts


def test_picker_returns_selected_container(monkeypatch) -> None:
    monkeypatch.setattr(_prompts, 'list_running_containers', lambda: ['db', 'odoo', 'redis'])

    with patch.object(_prompts.prompts, 'pick_one', return_value='odoo'):
        result = _prompts._handle_docker_container_selection('', 'desc', role='Odoo')
    assert result == 'odoo'


def test_picker_appends_configured_when_not_running(monkeypatch) -> None:
    """If the configured container isn't currently running, it is shown
    annotated so the user can still keep it without typing it again."""
    monkeypatch.setattr(_prompts, 'list_running_containers', lambda: ['db', 'redis'])

    captured = {}

    def fake_pick_one(message, choices):
        captured['choices'] = list(choices)
        # Simulate the user keeping the legacy entry.
        return choices[-1]

    with patch.object(_prompts.prompts, 'pick_one', side_effect=fake_pick_one):
        result = _prompts._handle_docker_container_selection(
            current_value='legacy_odoo',
            description='desc',
            role='Odoo',
        )

    assert any('legacy_odoo' in c for c in captured['choices'])
    assert result == 'legacy_odoo'  # annotation stripped


def test_picker_no_running_containers_falls_back_to_manual(monkeypatch) -> None:
    monkeypatch.setattr(_prompts, 'list_running_containers', lambda: [])
    with patch.object(_prompts.typer, 'prompt', return_value='odoo-manual'):
        result = _prompts._handle_docker_container_selection('', 'desc', role='Odoo')
    assert result == 'odoo-manual'


def test_picker_manual_q_cancels(monkeypatch) -> None:
    monkeypatch.setattr(_prompts, 'list_running_containers', lambda: [])
    with patch.object(_prompts.typer, 'prompt', return_value='q'):
        result = _prompts._handle_docker_container_selection('', 'desc')
    assert result is None


def test_picker_user_cancels_via_questionary(monkeypatch) -> None:
    monkeypatch.setattr(_prompts, 'list_running_containers', lambda: ['db'])
    # prompts.pick_one returns None when the user picks <create new>
    # (allow_create), but here we don't enable that. The realistic abort
    # path is OdooCLIError raised internally; we simulate the same.
    from otcli.domain.exceptions import OdooCLIError

    with patch.object(_prompts.prompts, 'pick_one', side_effect=OdooCLIError('cancel')):
        result = _prompts._handle_docker_container_selection('', 'desc')
    assert result is None
