"""Lightweight visual UI helpers for the CLI.

These helpers depend only on ``questionary`` (already a runtime dep) and
``typer`` (which re-exports ``click.style``). The goal is to give the
CLI a more friendly, sectioned look without pulling in ``rich`` or any
other extra dependency.

Convention:
- ``banner`` is for the very top of a long-running command (one per
  command at most).
- ``section`` introduces a sub-step of a wizard (numbered or named).
- ``info`` / ``hint`` / ``success`` / ``warn`` / ``error`` / ``muted``
  are inline messages used inside the body of a command.
- ``kv`` is for printing a configuration line in the form ``key: value``.

All helpers degrade gracefully when stdout is not a TTY (typer.style
returns plain text).
"""

from __future__ import annotations

from collections.abc import Iterable

import questionary
import typer

# --- Layout characters ---------------------------------------------------

# Layout characters (kept as escapes for portability across editors).

_BAR_HEAVY = '\u2501'
_BAR_LIGHT = '\u2500'
_BAR_DOUBLE = '\u2550'
_ARROW = '\u276f'
_CHECK = '\u2713'
_CROSS = '\u2717'
_BULLET = '\u2022'
_INFO = '\u24d8'


# --- Building blocks -----------------------------------------------------


def banner(title: str, *, subtitle: str | None = None) -> None:
    """Print a top-level banner.

    Designed to be used once at the start of a command (e.g. the
    interactive menu, the configuration wizard).
    """
    width = max(len(title), len(subtitle) if subtitle else 0) + 4
    bar = _BAR_DOUBLE * width
    typer.secho('')
    typer.secho(bar, fg=typer.colors.CYAN, bold=True)
    typer.secho(f'  {title}', fg=typer.colors.CYAN, bold=True)
    if subtitle:
        typer.secho(f'  {subtitle}', fg=typer.colors.BRIGHT_BLACK)
    typer.secho(bar, fg=typer.colors.CYAN, bold=True)


def section(title: str, *, step: int | None = None, total: int | None = None) -> None:
    """Print a numbered or plain section header inside a wizard.

    Examples::

        section("Identidad del cliente", step=1, total=4)
        section("Resumen")
    """
    prefix = f'[{step}/{total}] ' if step is not None and total is not None else ''
    typer.secho('')
    typer.secho(f'{_ARROW} {prefix}{title}', fg=typer.colors.BRIGHT_BLUE, bold=True)
    typer.secho(_BAR_LIGHT * (len(prefix) + len(title) + 2), fg=typer.colors.BRIGHT_BLACK)


def hint(message: str) -> None:
    """Italic, dim line used for descriptions next to a prompt."""
    questionary.print(f'  {message}', style='italic fg:#888888')


def info(message: str) -> None:
    typer.secho(f'  {_INFO} {message}', fg=typer.colors.BRIGHT_CYAN)


def success(message: str) -> None:
    typer.secho(f'  {_CHECK} {message}', fg=typer.colors.GREEN)


def warn(message: str) -> None:
    typer.secho(f'  ! {message}', fg=typer.colors.YELLOW)


def error(message: str) -> None:
    typer.secho(f'  {_CROSS} {message}', fg=typer.colors.RED, err=True)


def muted(message: str) -> None:
    typer.secho(f'  {message}', fg=typer.colors.BRIGHT_BLACK)


def kv(key: str, value: str, *, key_width: int = 22) -> None:
    """Render a key/value pair, with the key right-padded for alignment."""
    padded = key.ljust(key_width)
    typer.echo(
        typer.style(f'  {padded}', fg=typer.colors.BRIGHT_BLACK) + typer.style(f' {value}', fg=typer.colors.WHITE, bold=True)
    )


def bullet_list(items: Iterable[str]) -> None:
    for it in items:
        typer.secho(f'  {_BULLET} {it}')


def divider() -> None:
    typer.secho(_BAR_LIGHT * 60, fg=typer.colors.BRIGHT_BLACK)


def working(message: str) -> None:
    """Inline 'working on...' status (no spinner; we do not have rich)."""
    typer.secho(f'  ... {message}', fg=typer.colors.BRIGHT_BLACK, italic=True)
