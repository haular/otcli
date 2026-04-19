"""Centralised logging configuration for the CLI.

All diagnostic output goes to stderr so that the normal ``typer.echo``
messages (which go to stdout) and the log stream remain separable when a
caller pipes the output.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure(verbose: bool = False) -> None:
    """Configure the root logger for the otcli process.

    Idempotent: calling it twice does not add duplicate handlers.
    """
    global _CONFIGURED
    level = logging.DEBUG if verbose else logging.INFO

    if _CONFIGURED:
        logging.getLogger().setLevel(level)
        return

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt='%(asctime)s %(levelname)-7s %(name)s: %(message)s',
            datefmt='%H:%M:%S',
        )
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # Silence a couple of notoriously chatty third-party loggers unless the
    # user asked for verbose output.
    if not verbose:
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('docker').setLevel(logging.WARNING)

    _CONFIGURED = True
