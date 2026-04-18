"""
Utility functions for Docker operations.
"""
import logging
import sys
from typing import Optional

import docker
import typer
from docker.models.containers import Container

from odoo_task_cli.domain.exceptions import ContainerNotFoundError
from odoo_task_cli.domain.services import run

logger = logging.getLogger(__name__)


def _get_container(container_name: str) -> Container:
    """
    Get a Docker container by name.

    Args:
        container_name: Name of the container

    Returns:
        Container instance

    Raises:
        SystemExit: If the container doesn't exist or is not running
    """
    client = docker.DockerClient(base_url='unix://var/run/docker.sock', timeout=1000)
    try:
        container = client.containers.get(container_name)
        if container.status != "running":
            typer.echo(f"Error: Container '{container_name}' is not running.")
            sys.exit(1)
        return container
    except docker.errors.NotFound:
        typer.echo(f"Error: Container '{container_name}' does not exist.")
        sys.exit(1)


def _copy_file_from_container(container_name: str, src_path: str, dest_path: str) -> None:
    """
    Copy a file from a Docker container to the host.

    Args:
        container_name: Name of the container
        src_path: Source path in the container
        dest_path: Destination path on the host

    Raises:
        SystemExit: If the copy operation fails
    """
    command = ['docker', 'cp', f'{container_name}:{src_path}', dest_path, ]
    run(command)


def _copy_file_to_container(container_name: str, src_path: str, dest_path: str) -> None:
    """
    Copy a file from the host to a Docker container.

    Args:
        container_name: Name of the container
        src_path: Source path on the host
        dest_path: Destination path in the container

    Raises:
        SystemExit: If the copy operation fails
    """
    command = ['docker', 'cp', src_path, f'{container_name}:{dest_path}', ]
    run(command)


def _exec_in_container(
    container: Container,
    command: str,
    check: bool = True,
    **_legacy: object,
) -> Optional[object]:
    """Execute a command inside a Docker container.

    Args:
        container: Container instance.
        command: Command string to execute.
        check: When ``True`` (default), raise :class:`ContainerNotFoundError`
            on a non-zero exit code. When ``False``, the non-zero result is
            returned so the caller can decide what to do (useful for best-effort
            commands such as ``dropdb`` against a possibly-missing database).

    Additional keyword arguments are accepted for backwards compatibility
    (the parameter used to be called ``sys_exit``) but ignored.

    Returns:
        The ``exec_run`` result object. ``None`` is never returned on success.

    Raises:
        ContainerNotFoundError: If ``check`` is True and the command exits
            with a non-zero status, or if the Docker API raises an error.
    """
    # Backwards compatibility: some callers may still pass ``sys_exit``.
    if "sys_exit" in _legacy:
        check = bool(_legacy["sys_exit"])

    typer.echo(f"Executing in container: {command}")
    try:
        result = container.exec_run(command)
    except ContainerNotFoundError:
        raise
    except Exception as e:  # pragma: no cover - defensive
        raise ContainerNotFoundError(
            f"Error: Failed to execute command in container: {command}\n{e}"
        ) from e

    if result.exit_code != 0:
        output = result.output.decode("utf-8", errors="replace") if result.output else ""
        if check:
            raise ContainerNotFoundError(
                f"Error: Command execution failed in container: {command}\n"
                f"Output: {output}"
            )
        logger.warning(
            "Non-zero exit (%s) from container command (ignored): %s\n%s",
            result.exit_code,
            command,
            output,
        )
    return result


def list_running_containers() -> list[str]:
    """
    Lista los nombres de todos los contenedores Docker en ejecución.

    Returns:
        Una lista de nombres de contenedores en ejecución.
    """
    client = docker.from_env()
    try:
        containers = client.containers.list()
        return [c.name for c in containers]
    except Exception as e:
        typer.echo(f"Error al listar contenedores Docker: {e}")
        logger.error(f"Error al listar contenedores Docker: {e}")
        return []


def list_databases_in_container(container_name: str) -> list[str]:
    """
    Lista las bases de datos PostgreSQL dentro de un contenedor Docker.

    Args:
        container_name: El nombre del contenedor Docker.

    Returns:
        Una lista de nombres de bases de datos.
    """
    container = _get_container(container_name)
    if not container:
        return []

    # Ejecutar psql -l para listar las bases de datos
    # Usamos 'odoo' como usuario por defecto, puedes ajustarlo si es necesario
    command = "psql -U odoo -l -t -A"  # -t para solo tuplas, -A para sin alineación
    result = _exec_in_container(container, command, sys_exit=False)

    if result and result.exit_code == 0:
        output_lines = result.output.decode('utf-8').strip().split('\n')
        databases = []
        for line in output_lines:
            parts = line.split('|')
            if len(parts) > 0:
                db_name = parts[0].strip()
                # Filtrar bases de datos estándar como template0, template1, postgres
                if db_name and db_name not in ['template0', 'template1', 'postgres']:
                    databases.append(db_name)
        return databases
    else:
        raise ContainerNotFoundError(f"Error: No se pudieron listar las bases de datos en el contenedor '{container_name}'.")
