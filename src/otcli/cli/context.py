"""Application context object passed through the Typer command tree.

The Typer callback builds a single :class:`AppContext` per invocation
holding the resolved :class:`Settings` and :class:`ClientConfig`, then
attaches it to ``ctx.obj``. Each command pulls it back out with
:func:`get_context` and forwards the relevant attributes to the service
layer.
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

from otcli.domain.client_config import ClientConfig
from otcli.paths import Settings


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    client: ClientConfig


def get_context(ctx: typer.Context) -> AppContext:
    """Retrieve the :class:`AppContext` attached to ``ctx`` by the callback.

    Raises ``RuntimeError`` if the callback did not run (a programming
    error that should be visible immediately in tests).
    """
    if not isinstance(ctx.obj, AppContext):
        raise RuntimeError('AppContext is missing on ctx.obj; did the Typer callback run?')
    return ctx.obj
