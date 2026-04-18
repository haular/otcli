import typer

from otcli.infrastructure.docker import list_running_containers


def _prompt_for_value(
    key: str,
    current_value: str,
    description: str,
    prompt_message: str | None = None,
) -> str:
    typer.echo(f'\nDescripción: {description}')

    if prompt_message is None:
        prompt_message = f"Ingrese el valor para '{key}'"

    if current_value:
        typer.echo(f"El valor actual para '{key}' es: '{current_value}'")
        if not typer.confirm('¿Desea reemplazarlo?', default=False):
            return current_value

    return typer.prompt(prompt_message, default=current_value if current_value else '')


def _handle_docker_container_selection(current_value: str, description: str) -> str | None:
    typer.echo(f'\nDescripción: {description}')

    db_container_name = None
    while True:
        running_containers = list_running_containers()

        if not running_containers:
            typer.echo('No se encontraron contenedores Docker en ejecución.')
            db_container_name = typer.prompt(
                "Introduce el nombre del contenedor de la base de datos manualmente (o 'q' para cancelar)",
                default=current_value,
            )
            if db_container_name.lower() == 'q':
                return None
            break
        typer.echo('\nContenedores Docker en ejecución:')
        for i, container_name in enumerate(running_containers, 1):
            typer.echo(f'{i}. {container_name}')

        container_choice = typer.prompt(
            "Selecciona el número del contenedor de la base de datos o introduce el nombre (o 'q' para cancelar)",
            type=str,
            default=current_value,
        )
        if container_choice.lower() == 'q':
            return None

        if container_choice.isdigit():
            index = int(container_choice) - 1
            if 0 <= index < len(running_containers):
                db_container_name = running_containers[index]
                break
            typer.echo('Número de contenedor no válido. Se usará el valor ingresado.')
            db_container_name = container_choice
        else:
            db_container_name = container_choice
            break
    return db_container_name
