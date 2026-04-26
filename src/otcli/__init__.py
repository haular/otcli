"""otcli — Odoo Tasks CLI.

Public API:

* :class:`OdooCLIError` — base exception for tool-level errors.
* :class:`Settings` — filesystem path resolver (``~/.otcli_config`` by default,
  overridable with ``OTCLI_HOME``).
* :func:`backup_odoo_instance`, :func:`restore_odoo_database`,
  :func:`upgrade_database` — service entrypoints used by the CLI commands.

These names are stable across the 1.x line. Anything not re-exported here
is considered internal and may change without notice.
"""

from otcli.domain.exceptions import OdooCLIError
from otcli.paths import Settings
from otcli.services.backup import backup_odoo_instance
from otcli.services.restore import restore_odoo_database
from otcli.services.upgrade import upgrade_database

__all__ = [
    'OdooCLIError',
    'Settings',
    'backup_odoo_instance',
    'restore_odoo_database',
    'upgrade_database',
]

__version__ = '1.0.0a2'
