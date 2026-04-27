"""Interactive prompt helpers built on top of ``questionary``.

These helpers centralise the UX patterns used by the CLI. Use them in
CLI / wizard code; the service layer should remain free of UI
dependencies.

The ``OdooCLIError`` raised on ^C / ESC ensures aborts surface as
controlled exits rather than ``KeyboardInterrupt``.
"""

from __future__ import annotations

from collections.abc import Sequence

import questionary

from otcli.cli import ui
from otcli.domain.exceptions import OdooCLIError

# Sentinel returned by :func:`pick_one` when the user requests creation.
CREATE_NEW_SENTINEL = '<crear nuevo>'


def pick_one(
    prompt: str,
    items: Sequence[str],
    *,
    allow_create: bool = False,
    default: str | None = None,
) -> str | None:
    """Prompt the user to pick one entry from ``items``.

    Args:
        prompt: The question shown to the user.
        items: Choices to present. May be empty.
        allow_create: When ``True``, prepends a "<crear nuevo>" option
            and the function returns ``None`` if it is selected.
        default: Pre-selected item (must be present in ``items``).

    Returns:
        The selected item, or ``None`` if ``allow_create`` was set and
        the user picked the "<crear nuevo>" entry, or ``None`` if
        ``items`` is empty and ``allow_create`` is ``False``.

    Raises:
        OdooCLIError: If the user aborts the prompt (Ctrl-C / ESC).
    """
    if not items and not allow_create:
        return None
    choices: list[str] = list(items)
    if allow_create:
        choices = [CREATE_NEW_SENTINEL, *choices]

    answer = questionary.select(
        prompt,
        choices=choices,
        default=default if default in choices else None,
        use_shortcuts=False,
        qmark='?',
    ).ask()
    if answer is None:
        raise OdooCLIError('Operación cancelada por el usuario.')
    if allow_create and answer == CREATE_NEW_SENTINEL:
        return None
    return answer


def ask_text(
    prompt: str,
    *,
    default: str = '',
    description: str | None = None,
    current_value: str | None = None,
) -> str:
    """Plain-text input.

    Args:
        prompt: Short question shown to the user.
        default: Default value used when the user just hits Enter.
        description: Optional descriptive line printed before the prompt
            (italic, dim) so the user understands what is being asked.
        current_value: When set and non-empty, shown next to the prompt
            so the user knows the existing value. ``default`` falls back
            to ``current_value`` when not explicitly provided.
    """
    if description:
        ui.hint(description)
    if current_value:
        ui.muted(f'Valor actual: {current_value}')
        if not default:
            default = current_value
    answer = questionary.text(prompt, default=default, qmark='?').ask()
    if answer is None:
        raise OdooCLIError('Operación cancelada por el usuario.')
    return answer.strip()


def ask_required_text(
    prompt: str,
    *,
    default: str = '',
    description: str | None = None,
    current_value: str | None = None,
    error_message: str = 'Este campo es obligatorio.',
) -> str:
    """Like :func:`ask_text` but loops until the user types a non-empty value."""
    while True:
        value = ask_text(
            prompt,
            default=default,
            description=description,
            current_value=current_value,
        )
        if value:
            return value
        ui.warn(error_message)


def ask_secret(prompt: str) -> str:
    """Hidden-input prompt for credentials (e.g. master_pwd)."""
    answer = questionary.password(prompt, qmark='?').ask()
    if answer is None:
        raise OdooCLIError('Operación cancelada por el usuario.')
    return answer


def confirm(prompt: str, *, default: bool = False) -> bool:
    """Yes/no confirmation."""
    answer = questionary.confirm(prompt, default=default, qmark='?').ask()
    if answer is None:
        raise OdooCLIError('Operación cancelada por el usuario.')
    return bool(answer)
