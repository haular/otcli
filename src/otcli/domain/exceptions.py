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


class NeutralizeError(OdooCLIError):
    """Raised when the post-restore ``odoo-bin neutralize`` step fails.

    The restore itself is considered successful; this signals only the
    neutralization sub-step. Callers should log it as a warning and
    return normally so users can re-run neutralize manually.
    """
