"""Pure derivation of filesystem paths used by otcli.

This module performs **no** I/O at import time. Callers explicitly invoke
:meth:`Settings.ensure_dirs` when they need the directories to exist on
disk (typically once, from the Typer callback at CLI startup).

The location can be overridden via the ``OTCLI_HOME`` environment variable
for use in CI, sandboxes, or alternative deployments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved filesystem layout for an otcli installation.

    Attributes:
        app_data_dir: The root directory for all otcli state. Defaults to
            ``$HOME/.otcli_config`` and can be overridden by setting
            ``OTCLI_HOME``.
    """

    app_data_dir: Path

    @classmethod
    def from_env(cls) -> Settings:
        """Build ``Settings`` from the current process environment.

        Honours ``OTCLI_HOME`` if set; otherwise falls back to
        ``$HOME/.otcli_config``.
        """
        override = os.environ.get('OTCLI_HOME')
        if override:
            return cls(app_data_dir=Path(override))
        return cls(app_data_dir=Path.home() / '.otcli_config')

    @property
    def clients_config_dir(self) -> Path:
        """Directory holding per-client TOML configuration files."""
        return self.app_data_dir / 'clientes'

    @property
    def backups_dir(self) -> Path:
        """Directory where ``otcli backup`` writes its zip archives."""
        return self.app_data_dir / 'backups'

    def ensure_dirs(self) -> None:
        """Create the data directories on disk if they don't already exist.

        Idempotent: calling this multiple times is safe.
        """
        self.clients_config_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)
