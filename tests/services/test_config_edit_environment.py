"""``environment`` must be part of the interactive client configuration flow.

``infrastructure/upgrade.run_upgrade`` reads ``config.environment`` to pass
it as a positional argument to the upstream ``upgrade.odoo.com`` script.
Before this fix, the field was never asked for during ``edit_configuration``,
so any first-time upgrade attempt raised ``AttributeError`` from a remote
location in the call stack.
"""

from __future__ import annotations

from otcli.services.config_edit import CONFIG_FIELDS_ORDER, DESCRIPTIONS


def test_environment_is_part_of_interactive_flow() -> None:
    assert (
        'environment' in CONFIG_FIELDS_ORDER
    ), "'environment' must be in CONFIG_FIELDS_ORDER so the interactive editor asks the user for it."


def test_environment_has_a_description() -> None:
    assert 'environment' in DESCRIPTIONS
    assert DESCRIPTIONS['environment']  # non-empty string


def test_legacy_linked_production_client_removed() -> None:
    """Dead code: the field was never read or asked for."""
    assert 'linked_production_client' not in DESCRIPTIONS
    assert 'linked_production_client' not in CONFIG_FIELDS_ORDER
