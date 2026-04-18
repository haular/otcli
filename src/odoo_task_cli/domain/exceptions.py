class OdooCLIError(Exception):
    """Base exception for Odoo CLI Tool errors."""

    pass


class ContainerNotFoundError(OdooCLIError):
    """Raised when a Docker container is not found."""

    pass


class GitCheckoutError(OdooCLIError):
    """Raised when a Git checkout operation fails."""

    pass
