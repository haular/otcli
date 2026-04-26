"""Low-level prompt helpers for the configuration editor.

These wrap the user-facing typer prompts and the questionary-based
container picker. The legacy ``_prompt_for_value`` is still in use for
plain text fields (it knows how to keep the previous value when the
user declines to overwrite).
"""

from __future__ import annotations

import typer

from otcli.cli import prompts
from otcli.domain.exceptions import OdooCLIError
from otcli.infrastructure.docker import list_running_containers


def _prompt_for_value(
    key: str,
    current_value: str,
    description: str,
    prompt_message: str | None = None,
) -> str:
    typer.echo(f'\nDescripción: {description}')

    if prompt_message is None:
        prompt_message = f"Ingrese el valor para '{key}'"

    if current_value:
        typer.echo(f"El valor actual para '{key}' es: '{current_value}'")
        if not typer.confirm('¿Desea reemplazarlo?', default=False):
            return current_value

    return typer.prompt(prompt_message, default=current_value if current_value else '')


def _handle_docker_container_selection(
    current_value: str,
    description: str,
    role: str = 'database',
) -> str | None:
    """Pick one of the running Docker containers, or type a name manually.

    Args:
        current_value: The previously-configured container name (used as
            the default when the user types a name manually).
        description: Field description shown to the user before the prompt.
        role: Free-form label inserted into prompt text so the user knows
            which container they're picking ('database', 'Odoo', ...).

    Returns:
        The selected container name, or ``None`` if the user cancelled.
    """
    typer.echo(f'\nDescripción: {description}')

    running = list_running_containers()
    if not running:
        typer.echo('No running Docker containers detected.')
        manual = typer.prompt(
            f"Type the {role} container name manually (or 'q' to cancel)",
            default=current_value,
        )
        if manual.lower() == 'q':
            return None
        return manual

    # Show the current value in the choices list so the user can keep it
    # easily even if the running set differs from what was configured.
    choices = list(running)
    if current_value and current_value not in choices:
        choices.append(f'{current_value}  (configured, not currently running)')

    try:
        selected = prompts.pick_one(
            f'Select the {role} container',
            choices,
        )
    except OdooCLIError:
        return None

    if selected is None:
        return None

    # Strip the annotation we added for the configured-but-not-running entry.
    return selected.split('  (', 1)[0]
