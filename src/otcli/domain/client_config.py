"""Typed, validated client configuration for otcli.

The configuration is grouped into four required sections:

    [client]
    technical_name = "acme"
    filestore_dir  = "/var/lib/odoo/filestore"

    [database]
    db_name = "acme"          # optional; defaults to client.technical_name

    [docker]
    db_container   = "db"
    odoo_container = "odoo"
    odoo_bin_path  = ""       # optional; empty means auto-detect

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
_ALLOWED_TOP_LEVEL_SECTIONS = frozenset({'client', 'database', 'docker', 'upgrade'})


@dataclass(frozen=True, slots=True)
class Database:
    db_name: str = ''  # empty means: defer to ClientConfig.technical_name


@dataclass(frozen=True, slots=True)
class Docker:
    db_container: str
    odoo_container: str
    odoo_bin_path: str = ''  # empty means: auto-detect inside the container


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
    upgrade: Upgrade

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ClientConfig:
        """Validate and build a :class:`ClientConfig` from a ``dict``."""
        unknown_top = set(raw.keys()) - _ALLOWED_TOP_LEVEL_SECTIONS
        if unknown_top:
            raise ClientConfigError(
                f'Unrecognised top-level keys {sorted(unknown_top)}. This may '
                f'be a legacy pre-1.0 client TOML; please reconfigure with '
                f"`otcli interactive` (option 'Editar Configuración'). "
                f'See README \u2192 "Upgrading from pre-1.0 installations".'
            )

        try:
            client = raw['client']
        except KeyError as err:
            raise ClientConfigError(f'Missing required section: {err.args[0]}') from err
        try:
            docker_raw = raw['docker']
        except KeyError as err:
            raise ClientConfigError(f'Missing required section: {err.args[0]}') from err
        try:
            upgrade_raw = raw['upgrade']
        except KeyError as err:
            raise ClientConfigError(f'Missing required section: {err.args[0]}') from err

        # ``database`` is now optional: its only field (db_name) defaults to
        # client.technical_name. Treat a missing section as an empty dict.
        database_raw = raw.get('database', {})

        try:
            technical_name = client['technical_name']
            filestore_dir = client['filestore_dir']
        except KeyError as err:
            raise ClientConfigError(f'client.{err.args[0]} is required') from err

        environment = upgrade_raw.get('environment', '')
        if environment and environment not in _ALLOWED_ENVIRONMENTS:
            raise ClientConfigError(
                f'upgrade.environment must be one of {sorted(_ALLOWED_ENVIRONMENTS)}; got {environment!r}'
            )

        db = Database(db_name=database_raw.get('db_name') or technical_name)
        dk = Docker(
            db_container=docker_raw.get('db_container', ''),
            odoo_container=docker_raw.get('odoo_container', ''),
            odoo_bin_path=docker_raw.get('odoo_bin_path', ''),
        )
        up = Upgrade(
            target=upgrade_raw.get('target', ''),
            code_subscription=upgrade_raw.get('code_subscription', ''),
            environment=environment,
        )

        return cls(
            technical_name=technical_name,
            filestore_dir=filestore_dir,
            database=db,
            docker=dk,
            upgrade=up,
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
            'upgrade': asdict(self.upgrade),
        }
