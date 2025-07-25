# Herramienta CLI de Odoo

Esta es una herramienta de línea de comandos (CLI) diseñada para automatizar el proceso de migración de bases de datos
de Odoo de una versión a otra. Se encarga de tareas como copias de seguridad, restauración y ejecución de scripts de
actualización.

## Estructura del Proyecto

El proyecto está organizado de la siguiente manera:

- **`src/`**: Contiene el código fuente principal de la herramienta CLI.
    - `odoo_task_cli/`: El paquete principal de la herramienta CLI.
    - `__main__.py`: Punto de entrada para la aplicación CLI.
    - `cli/`: Contiene la interfaz de línea de comandos (CLI) de la aplicación.
        - `main.py`: Define los comandos y la lógica principal de la CLI usando Typer.
    - `config.py`: Maneja la gestión de la configuración de la aplicación.
    - `domain/`: Contiene la lógica de negocio central, modelos de datos y excepciones personalizadas.
        - `models.py`: Definiciones de modelos de datos.
        - `exceptions.py`: Definición de excepciones personalizadas para la herramienta.
        - `services.py`: Funciones de utilidad para la ejecución de comandos.
        - `utils.py`: Funciones de utilidad generales.
    - `infrastructure/`: Gestiona las interacciones con sistemas externos y servicios de bajo nivel.
        - `config_manager.py`: Manejo de la carga y guardado de configuraciones de cliente.
        - `db_client.py`: Funciones para operaciones de base de datos (backup).
        - `docker_client.py`: Funciones para interactuar con Docker.
        - `git_client.py`: Funciones para interactuar con Git.
        - `odoo_client.py`: Funciones para interactuar con la API de Odoo y el servicio de actualización.
    - `services/`: Contiene la implementación de los casos de uso de la aplicación (lógica de negocio de alto nivel).
        - `backup_odoo_service.py`: Lógica para realizar backups de Odoo.
        - `edit_configuration_service.py`: Lógica para la edición interactiva de la configuración.
        - `edit_configuration_helpers.py`: Funciones auxiliares para la edición de configuración.
        - `restore_database_service.py`: Lógica para la restauración de bases de datos.
        - `upgrade_database_service.py`: Lógica para la actualización de bases de datos.
    - **`tests/`**: Contiene las pruebas para la aplicación.
- **`pyproject.toml`**: Define los metadatos y dependencias del proyecto.

## Configuración e Instalación

1. **Prerrequisitos:**
    * Python 3.12 o superior
    * `uv` para la gestión de paquetes y entornos virtuales.
    * Git instalado y configurado.

2. **Instalación:**
    * Clona el repositorio: `git clone <URL_del_repositorio>`
    * Navega al directorio del proyecto: `cd odoo_cli_tool`
    * Crea un entorno virtual e instala las dependencias con `uv`:
      ```bash
      uv venv
      source .venv/bin/activate
      uv pip install -e .
      ```

## Uso

Para usar la herramienta CLI de Odoo, ejecuta el siguiente comando:

```bash
otcli <comando> [opciones]
```

Al iniciar la herramienta, si no hay clientes configurados o si seleccionas la opción '0', se te guiará para crear una
nueva configuración de cliente de forma interactiva.

Para obtener una lista de los comandos disponibles, puedes ejecutar:

```bash
otcli --help
```

## Configuración

La herramienta utiliza un archivo de configuración ubicado en `~/.odoo_task_cli_config/clientes/`. Cada cliente tendrá
su propio archivo TOML (por ejemplo, `mi_cliente.toml`).

## Desarrollo

Para configurar el entorno de desarrollo, sigue estos pasos:

1. **Instalar dependencias de desarrollo:**
   ```bash
   uv pip install -e ".[dev]"
   ```

2. **Ejecutar pruebas:**
   ```bash
   pytest
   ```
