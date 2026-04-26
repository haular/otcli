"""Interactive prompt helpers built on top of ``questionary``.

These helpers centralise the UX patterns previously scattered across
several hand-rolled selectors (``select_client``, ``_select_backup_file``,
the command-management menu, …). Use them in CLI code; the service layer
should remain free of UI dependencies.

The ``OdooCLIError`` raised on ^C / ESC ensures aborts surface as
controlled exits rather than ``KeyboardInterrupt``.
"""

from __future__ import annotations

from collections.abc import Sequence

import questionary

from otcli.domain.exceptions import OdooCLIError

# Sentinel returned by :func:`pick_one` when the user requests creation.
CREATE_NEW_SENTINEL = '<create new>'


def pick_one(
    prompt: str,
    items: Sequence[str],
    *,
    allow_create: bool = False,
) -> str | None:
    """Prompt the user to pick one entry from ``items``.

    Args:
        prompt: The question shown to the user.
        items: Choices to present. May be empty.
        allow_create: When ``True``, prepends a "<create new>" option
            and the function returns ``None`` if it is selected.

    Returns:
        The selected item, or ``None`` if ``allow_create`` was set and
        the user picked the "<create new>" entry, or ``None`` if
        ``items`` is empty and ``allow_create`` is ``False``.

    Raises:
        OdooCLIError: If the user aborts the prompt (Ctrl-C / ESC).
    """
    if not items and not allow_create:
        return None
    choices: list[str] = list(items)
    if allow_create:
        choices = [CREATE_NEW_SENTINEL, *choices]

    answer = questionary.select(prompt, choices=choices).ask()
    if answer is None:
        raise OdooCLIError('Operation cancelled by user.')
    if allow_create and answer == CREATE_NEW_SENTINEL:
        return None
    return answer


def ask_text(
    prompt: str,
    *,
    default: str = '',
    description: str | None = None,
) -> str:
    """Plain-text input with an optional default value."""
    if description:
        questionary.print(description, style='italic')
    answer = questionary.text(prompt, default=default).ask()
    if answer is None:
        raise OdooCLIError('Operation cancelled by user.')
    return answer


def ask_secret(prompt: str) -> str:
    """Hidden-input prompt for credentials (e.g. master_pwd)."""
    answer = questionary.password(prompt).ask()
    if answer is None:
        raise OdooCLIError('Operation cancelled by user.')
    return answer


def confirm(prompt: str, *, default: bool = False) -> bool:
    """Yes/no confirmation."""
    answer = questionary.confirm(prompt, default=default).ask()
    if answer is None:
        raise OdooCLIError('Operation cancelled by user.')
    return bool(answer)
