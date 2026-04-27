"""Typed, validated client configuration for otcli.

The configuration is grouped into five sections (one optional):

    [client]
    technical_name = "acme"
    filestore_dir  = "/var/lib/odoo/filestore"

    [database]
    db_name = "acme"          # optional; defaults to client.technical_name

    [docker]
    db_container = "db"       # PostgreSQL container

    [odoo]
    install_mode    = "docker"   # 'docker' | 'native' | 'source'
    container_name  = "odoo"     # required when install_mode='docker', else ignored
    odoo_bin_path   = ""         # path to odoo-bin; semantics depend on install_mode

    [upgrade]
    target            = "18.0"
    code_subscription = "..."
    environment       = "test"   # 'test' | 'production'

Pre-1.0 flat layouts (with keys like ``technical_client_name`` at the
top level instead of inside sections) are rejected at load time with
``ClientConfigError`` and a message instructing the user to reconfigure.
There is no automatic migration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from otcli.domain.exceptions import ClientConfigError

_ALLOWED_ENVIRONMENTS = frozenset({'test', 'production'})
_ALLOWED_INSTALL_MODES = frozenset({'docker', 'native', 'source'})
_ALLOWED_TOP_LEVEL_SECTIONS = frozenset({'client', 'database', 'docker', 'odoo', 'upgrade'})


@dataclass(frozen=True, slots=True)
class Database:
    db_name: str = ''  # empty means: defer to ClientConfig.technical_name


@dataclass(frozen=True, slots=True)
class Docker:
    db_container: str


@dataclass(frozen=True, slots=True)
class Odoo:
    """Where and how to invoke ``odoo-bin``.

    The ``install_mode`` discriminator determines how the other fields
    are interpreted:

    * ``docker``: ``container_name`` is the Odoo container; ``odoo_bin_path``
      is a path **inside** that container (empty means auto-detect).
      ``odoo_conf_path`` and ``python_executable`` are ignored (the
      container's image typically embeds its own configuration and
      Python interpreter).
    * ``native``: Odoo is installed on the host (Debian package or
      similar). ``odoo_bin_path`` is an absolute path on the host
      (empty means ``which odoo-bin`` then ``/usr/bin/odoo-bin``).
      ``odoo_conf_path`` is optional; if set it is forwarded to
      ``odoo-bin`` via ``-c <path>``. ``python_executable`` is also
      optional; setting it overrides the ``odoo-bin`` shebang and is
      useful when Odoo's dependencies live in a venv.
    * ``source``: Odoo cloned from GitHub. ``odoo_bin_path`` and
      ``odoo_conf_path`` are both required (without ``-c`` the script
      cannot reach Postgres). ``python_executable`` is **strongly
      recommended** because the ``odoo-bin`` shebang
      (``#!/usr/bin/env python3``) typically resolves to the system
      Python, which lacks Odoo's runtime dependencies. Point this at
      the Python in the venv where you ``pip install -r
      requirements.txt`` (e.g. ``/path/to/venv/bin/python3``).
    """

    install_mode: str
    container_name: str = ''
    odoo_bin_path: str = ''
    odoo_conf_path: str = ''
    python_executable: str = ''


@dataclass(frozen=True, slots=True)
class Upgrade:
    target: str
    code_subscription: str
    environment: str


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Top-level client configuration.

    Construct from a raw ``dict`` (typically parsed from TOML) via
    :meth:`from_dict`; produce one with :meth:`to_dict` to serialise.
    """

    technical_name: str
    filestore_dir: str
    database: Database
    docker: Docker
    odoo: Odoo
    upgrade: Upgrade

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ClientConfig:
        """Validate and build a :class:`ClientConfig` from a ``dict``."""
        _reject_legacy_top_level(raw)

        client = _require_section(raw, 'client')
        docker_raw = _require_section(raw, 'docker')
        odoo_raw = _require_section(raw, 'odoo')
        upgrade_raw = _require_section(raw, 'upgrade')
        database_raw = raw.get('database', {})  # optional

        technical_name, filestore_dir = _client_fields(client)
        upgrade = _build_upgrade(upgrade_raw)
        odoo = _build_odoo(odoo_raw)

        return cls(
            technical_name=technical_name,
            filestore_dir=filestore_dir,
            database=Database(db_name=database_raw.get('db_name') or technical_name),
            docker=Docker(db_container=docker_raw.get('db_container', '')),
            odoo=odoo,
            upgrade=upgrade,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain ``dict`` suitable for TOML output."""
        return {
            'client': {
                'technical_name': self.technical_name,
                'filestore_dir': self.filestore_dir,
            },
            'database': {
                'db_name': self.database.db_name or self.technical_name,
            },
            'docker': asdict(self.docker),
            'odoo': asdict(self.odoo),
            'upgrade': asdict(self.upgrade),
        }


# --- Private validation helpers ------------------------------------------


def _reject_legacy_top_level(raw: dict[str, Any]) -> None:
    unknown = set(raw.keys()) - _ALLOWED_TOP_LEVEL_SECTIONS
    if unknown:
        raise ClientConfigError(
            f'Unrecognised top-level keys {sorted(unknown)}. This may be a '
            f'legacy pre-1.0 client TOML; please reconfigure with `otcli '
            f"interactive` (option 'Editar Configuración'). "
            f'See README \u2192 "Upgrading from pre-1.0 installations".'
        )


def _require_section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    try:
        return raw[name]
    except KeyError as err:
        raise ClientConfigError(f'Missing required section: {name}') from err


def _client_fields(client: dict[str, Any]) -> tuple[str, str]:
    try:
        return client['technical_name'], client['filestore_dir']
    except KeyError as err:
        raise ClientConfigError(f'client.{err.args[0]} is required') from err


def _build_upgrade(raw: dict[str, Any]) -> Upgrade:
    environment = raw.get('environment', '')
    if environment and environment not in _ALLOWED_ENVIRONMENTS:
        raise ClientConfigError(f'upgrade.environment must be one of {sorted(_ALLOWED_ENVIRONMENTS)}; got {environment!r}')
    return Upgrade(
        target=raw.get('target', ''),
        code_subscription=raw.get('code_subscription', ''),
        environment=environment,
    )


def _build_odoo(raw: dict[str, Any]) -> Odoo:
    install_mode = raw.get('install_mode', '')
    if not install_mode:
        raise ClientConfigError('odoo.install_mode is required')
    if install_mode not in _ALLOWED_INSTALL_MODES:
        raise ClientConfigError(f'odoo.install_mode must be one of {sorted(_ALLOWED_INSTALL_MODES)}; got {install_mode!r}')

    container_name = raw.get('container_name', '')
    odoo_bin_path = raw.get('odoo_bin_path', '')
    odoo_conf_path = raw.get('odoo_conf_path', '')
    python_executable = raw.get('python_executable', '')

    if install_mode == 'docker' and not container_name:
        raise ClientConfigError("odoo.container_name is required when install_mode='docker'")
    if install_mode == 'source' and not odoo_bin_path:
        raise ClientConfigError(
            "odoo.odoo_bin_path is required when install_mode='source' (point to the absolute path of odoo-bin in your clone)"
        )
    if install_mode == 'source' and not odoo_conf_path:
        raise ClientConfigError(
            "odoo.odoo_conf_path is required when install_mode='source' (odoo-bin needs -c <conf> to reach Postgres)"
        )

    return Odoo(
        install_mode=install_mode,
        container_name=container_name,
        odoo_bin_path=odoo_bin_path,
        odoo_conf_path=odoo_conf_path,
        python_executable=python_executable,
    )
