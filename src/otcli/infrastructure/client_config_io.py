"""Pure load/save of :class:`ClientConfig` to TOML files.

Reads use stdlib :mod:`tomllib`; writes use :mod:`tomli_w`. Legacy
runtime keys persisted by pre-1.0 versions raise
:class:`ClientConfigError` at load time so the bug that motivated 1.0
cannot resurface.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import ClientConfigError


def list_clients(clients_dir: Path) -> list[str]:
    """Return the sorted list of client names registered under ``clients_dir``."""
    if not clients_dir.is_dir():
        return []
    return sorted(p.stem for p in clients_dir.glob('*.toml'))


def load(name: str, clients_dir: Path) -> ClientConfig:
    """Load and validate a single client configuration."""
    path = clients_dir / f'{name}.toml'
    if not path.is_file():
        raise ClientConfigError(f'Client configuration not found: {path}')
    with path.open('rb') as fh:
        raw = tomllib.load(fh)
    return ClientConfig.from_dict(raw)


def save(cfg: ClientConfig, clients_dir: Path) -> Path:
    """Serialise ``cfg`` to ``<clients_dir>/<technical_name>.toml``.

    Returns the absolute path to the written file. Creates ``clients_dir``
    (and any intermediate directories) on demand.
    """
    clients_dir.mkdir(parents=True, exist_ok=True)
    path = clients_dir / f'{cfg.technical_name}.toml'
    with path.open('wb') as fh:
        tomli_w.dump(cfg.to_dict(), fh)
    return path
