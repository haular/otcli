"""Exception hierarchy for otcli."""

from __future__ import annotations


class OdooCLIError(Exception):
    """Base exception for Odoo CLI Tool errors."""


class ContainerNotFoundError(OdooCLIError):
    """Raised when a Docker container is not found or its command failed."""


class ClientConfigError(OdooCLIError):
    """Raised when a client TOML is malformed, missing required fields,
    or contains values that fail validation.
    """
