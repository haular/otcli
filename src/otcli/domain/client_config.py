"""Typed, validated client configuration for otcli.

The configuration is grouped into four required sections plus an optional
list of post-restore commands:

    [client]
    technical_name = "acme"
    filestore_dir  = "/var/lib/odoo/filestore"

    [database]
    url        = "http://localhost:8069"
    master_pwd = "..."
    db_name    = "acme"          # optional; defaults to client.technical_name

    [docker]
    db_container   = "db"
    odoo_container = "odoo"

    [upgrade]
    target            = "18.0"
    code_subscription = "..."
    environment       = "test"   # 'test' | 'production'
    repo_path         = "/repo"

    [[commands]]
    type  = "hash"
    value = "abc123"

    [[commands]]
    type  = "shell"
    value = ["docker", "ps", "-a"]

Pre-1.0 flat layouts (with keys like ``technical_client_name`` at the
top level instead of inside sections) are rejected at load time with
``ClientConfigError`` and a message instructing the user to reconfigure.
There is no automatic migration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from otcli.domain.exceptions import ClientConfigError

_ALLOWED_ENVIRONMENTS = frozenset({'test', 'production'})
_ALLOWED_TOP_LEVEL_SECTIONS = frozenset({'client', 'database', 'docker', 'upgrade', 'commands'})


@dataclass(frozen=True, slots=True)
class Database:
    url: str
    master_pwd: str
    db_name: str = ''  # empty means: defer to ClientConfig.technical_name


@dataclass(frozen=True, slots=True)
class Docker:
    db_container: str
    odoo_container: str


@dataclass(frozen=True, slots=True)
class Upgrade:
    target: str
    code_subscription: str
    environment: str
    repo_path: str


@dataclass(frozen=True, slots=True)
class CommandHash:
    """Recorded git hash to apply after restore."""

    value: str
    type: str = 'hash'


@dataclass(frozen=True, slots=True)
class CommandShell:
    """Recorded shell command to run after restore."""

    value: list[str]
    type: str = 'shell'


Command = CommandHash | CommandShell


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
    commands: tuple[Command, ...] = field(default=())

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ClientConfig:
        """Validate and build a :class:`ClientConfig` from a ``dict``.

        Raises :class:`ClientConfigError` with a precise message on any
        validation failure.
        """
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
            database_raw = raw['database']
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

        try:
            technical_name = client['technical_name']
            filestore_dir = client['filestore_dir']
        except KeyError as err:
            raise ClientConfigError(f'client.{err.args[0]} is required') from err

        environment = upgrade_raw.get('environment', '')
        if environment and environment not in _ALLOWED_ENVIRONMENTS:
            raise ClientConfigError(
                f'upgrade.environment must be one of ' f'{sorted(_ALLOWED_ENVIRONMENTS)}; got {environment!r}'
            )

        db = Database(
            url=database_raw.get('url', ''),
            master_pwd=database_raw.get('master_pwd', ''),
            db_name=database_raw.get('db_name') or technical_name,
        )
        dk = Docker(
            db_container=docker_raw.get('db_container', ''),
            odoo_container=docker_raw.get('odoo_container', ''),
        )
        up = Upgrade(
            target=upgrade_raw.get('target', ''),
            code_subscription=upgrade_raw.get('code_subscription', ''),
            environment=environment,
            repo_path=upgrade_raw.get('repo_path', ''),
        )
        cmds = tuple(_parse_command(c) for c in raw.get('commands', []))

        return cls(
            technical_name=technical_name,
            filestore_dir=filestore_dir,
            database=db,
            docker=dk,
            upgrade=up,
            commands=cmds,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain ``dict`` suitable for TOML output."""
        return {
            'client': {
                'technical_name': self.technical_name,
                'filestore_dir': self.filestore_dir,
            },
            'database': {
                'url': self.database.url,
                'master_pwd': self.database.master_pwd,
                'db_name': self.database.db_name or self.technical_name,
            },
            'docker': asdict(self.docker),
            'upgrade': asdict(self.upgrade),
            'commands': [asdict(c) for c in self.commands],
        }


def _parse_command(raw: dict[str, Any]) -> Command:
    cmd_type = raw.get('type')
    if cmd_type == 'hash':
        try:
            return CommandHash(value=raw['value'])
        except KeyError as err:
            raise ClientConfigError(f'commands.{err.args[0]} is required for hash commands') from err
    if cmd_type == 'shell':
        try:
            value = raw['value']
        except KeyError as err:
            raise ClientConfigError(f'commands.{err.args[0]} is required for shell commands') from err
        if not isinstance(value, list) or not all(isinstance(part, str) for part in value):
            raise ClientConfigError(f'commands.value for a shell command must be a list of strings; got {value!r}')
        return CommandShell(value=list(value))
    raise ClientConfigError(f"Unknown command type {cmd_type!r}; expected 'hash' or 'shell'.")
