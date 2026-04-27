"""Interactive client configuration wizard.

This module presents prompts to the user, validates input, and returns a
typed :class:`ClientConfig`. The CLI layer is responsible for actually
persisting the result via
:func:`otcli.infrastructure.client_config_io.save`.

The wizard is laid out in four sequential sections:

    [1/4] Identidad del cliente   -> technical_name
    [2/4] Base de datos           -> docker DB container
    [3/4] Instalación de Odoo     -> install_mode + mode-specific fields
    [4/4] Filestore               -> filestore_dir (auto-detect on docker)

Upgrade-related fields (``upgrade_target``, ``code_subscription``,
``environment``) are NOT prompted here anymore: they live in the
upgrade-specific wizard (:mod:`otcli.services.upgrade_config`) and are
asked just-in-time when the user actually triggers a database upgrade.
"""

from __future__ import annotations

import logging
import os

from otcli.cli import prompts, ui
from otcli.domain.client_config import (
    ClientConfig,
    Database,
    Docker,
    Odoo,
    Upgrade,
)
from otcli.infrastructure.docker import (
    find_odoo_conf_in_container,
    list_container_mounts,
    map_container_path_to_host,
    parse_data_dir_from_odoo_conf,
)
from otcli.services._prompts import _handle_docker_container_selection

logger = logging.getLogger(__name__)

_ALLOWED_INSTALL_MODES = ('docker', 'native', 'source')

# --- Field descriptions (kept as a dict so tests can pin them) -----------
DESCRIPTIONS: dict[str, str] = {
    'technical_client_name': (
        'Nombre técnico del cliente. Se usará como nombre de la base de datos y como subdirectorio dentro del filestore.'
    ),
    'db_container_name': 'Contenedor Docker que ejecuta la base de datos PostgreSQL.',
    'odoo_container_name': 'Contenedor Docker que ejecuta la instancia de Odoo.',
    'odoo_install_mode': (
        "Cómo está instalado Odoo en este host: 'docker' (en un contenedor), "
        "'native' (paquete del sistema) o 'source' (clon de GitHub)."
    ),
    'odoo_bin_path_docker': ("Ruta absoluta a 'odoo-bin' DENTRO del contenedor Odoo. Déjalo vacío para auto-detectar."),
    'odoo_bin_path_native': (
        "Ruta absoluta a 'odoo-bin' en el host. Déjalo vacío para auto-detectar (`which odoo-bin` y luego /usr/bin/odoo-bin)."
    ),
    'odoo_bin_path_source': ("Ruta absoluta a 'odoo-bin' dentro del clon de Odoo en el host (ej. /home/user/odoo/odoo-bin)."),
    'odoo_conf_path_native': (
        'Ruta absoluta a un archivo odoo.conf en el host. Opcional: el paquete Debian lee /etc/odoo/odoo.conf por defecto.'
    ),
    'odoo_conf_path_source': ('Ruta absoluta a un archivo odoo.conf en el host (ej. /home/user/projects/cliente/odoo.conf).'),
    'python_executable_native': (
        'Ruta absoluta al intérprete Python para invocar odoo-bin. Opcional: '
        'déjalo vacío para usar el shebang. Útil cuando Odoo vive en un venv.'
    ),
    'python_executable_source': (
        'Ruta absoluta al intérprete Python con las dependencias de Odoo '
        'instaladas (ej. /home/user/venvs/18.0/.venv/bin/python3).'
    ),
    'filestore_dir': (
        'Directorio del HOST donde residen los filestores. otcli añadirá automáticamente '
        'el subdirectorio del cliente (technical_name). En modo Docker se intenta '
        'auto-detectar desde el odoo.conf y los volúmenes del contenedor.'
    ),
    # upgrade-related descriptions (used by the upgrade wizard)
    'environment': "Entorno objetivo del servicio de actualización: 'test' o 'production'.",
    'upgrade_target': "Versión Odoo destino para la migración (ej. '18.0').",
    'code_subscription': 'Código de suscripción de Odoo para el servicio de actualización.',
}


_TOTAL_STEPS = 4


def edit_configuration_interactive(existing: ClientConfig | None = None) -> ClientConfig:
    """Walk the user through every configurable field and return a ClientConfig.

    Pass ``existing`` to pre-fill prompts when editing a known client.
    Pass ``None`` (the default) when registering a brand-new client.
    """
    if existing is None:
        ui.banner('Nuevo cliente', subtitle='Configuremos los datos básicos paso a paso.')
    else:
        ui.banner(
            'Editar configuración',
            subtitle=f"Cliente: '{existing.technical_name}'",
        )

    # --- Step 1: identity ------------------------------------------------
    ui.section('Identidad del cliente', step=1, total=_TOTAL_STEPS)
    technical_client_name = _ask_technical_name(existing)

    # --- Step 2: install mode + Odoo placement --------------------------
    ui.section('Instalación de Odoo', step=2, total=_TOTAL_STEPS)
    install_mode = _ask_install_mode(existing)

    odoo_container_name = ''
    odoo_bin_path = ''
    odoo_conf_path = ''
    python_executable = ''
    detected_filestore_default = ''

    if install_mode == 'docker':
        odoo_container_name = _ask_odoo_container(existing)
        odoo_bin_path = _ask_odoo_bin_path(existing, mode='docker')
        # Try to read odoo.conf inside the container so we can both
        # forget asking the user and pre-compute filestore_dir.
        odoo_conf_path, detected_filestore_default = _autodetect_from_docker_conf(odoo_container_name)
    elif install_mode == 'native':
        odoo_bin_path = _ask_odoo_bin_path(existing, mode='native')
        odoo_conf_path = _ask_odoo_conf_path(existing, mode='native')
        python_executable = _ask_python_executable(existing, mode='native')
        detected_filestore_default = _autodetect_filestore_from_host_conf(odoo_conf_path)
    elif install_mode == 'source':
        odoo_bin_path = _ask_odoo_bin_path(existing, mode='source')
        odoo_conf_path = _ask_odoo_conf_path(existing, mode='source')
        python_executable = _ask_python_executable(existing, mode='source')
        detected_filestore_default = _autodetect_filestore_from_host_conf(odoo_conf_path)

    # --- Step 3: database container -------------------------------------
    ui.section('Base de datos', step=3, total=_TOTAL_STEPS)
    db_container_name = _ask_db_container(existing)

    # --- Step 4: filestore ----------------------------------------------
    ui.section('Filestore', step=4, total=_TOTAL_STEPS)
    filestore_dir = _ask_filestore_dir(
        existing,
        odoo_container_name=odoo_container_name if install_mode == 'docker' else '',
        autodetected_default=detected_filestore_default,
    )

    cfg = ClientConfig(
        technical_name=technical_client_name,
        filestore_dir=filestore_dir,
        database=Database(db_name=technical_client_name),
        docker=Docker(db_container=db_container_name),
        odoo=Odoo(
            install_mode=install_mode,
            container_name=odoo_container_name,
            odoo_bin_path=odoo_bin_path,
            odoo_conf_path=odoo_conf_path,
            python_executable=python_executable,
        ),
        upgrade=_preserve_upgrade(existing),
    )

    _print_summary(cfg)
    return cfg


# --- Prompt helpers -------------------------------------------------------


def _ask_technical_name(existing: ClientConfig | None) -> str:
    current = existing.technical_name if existing else ''
    return prompts.ask_required_text(
        'Nombre técnico del cliente:',
        default=current,
        description=DESCRIPTIONS['technical_client_name'],
        current_value=current or None,
    )


def _ask_install_mode(existing: ClientConfig | None) -> str:
    current = existing.odoo.install_mode if existing else ''
    ui.hint(DESCRIPTIONS['odoo_install_mode'])
    choice = prompts.pick_one(
        '¿Cómo está instalado Odoo?',
        list(_ALLOWED_INSTALL_MODES),
        default=current or None,
    )
    return choice or current


def _ask_db_container(existing: ClientConfig | None) -> str:
    current = existing.docker.db_container if existing else ''
    container = _handle_docker_container_selection(
        current,
        DESCRIPTIONS['db_container_name'],
        role='base de datos (PostgreSQL)',
    )
    if container is None:
        ui.warn('Selección cancelada; se conserva el valor actual.')
        return current
    return container


def _ask_odoo_container(existing: ClientConfig | None) -> str:
    current = existing.odoo.container_name if existing else ''
    container = _handle_docker_container_selection(
        current,
        DESCRIPTIONS['odoo_container_name'],
        role='Odoo',
    )
    if container is None:
        ui.warn('Selección cancelada; se conserva el valor actual.')
        return current
    return container


def _ask_odoo_bin_path(existing: ClientConfig | None, *, mode: str) -> str:
    """Ask for ``odoo-bin`` path with mode-specific guidance.

    For ``docker`` and ``native`` an empty answer is fine (auto-detect);
    for ``source`` we re-prompt until the user provides a non-empty
    absolute path.
    """
    current = existing.odoo.odoo_bin_path if existing else ''
    description = DESCRIPTIONS[f'odoo_bin_path_{mode}']

    if mode == 'source':
        return prompts.ask_required_text(
            'Ruta absoluta a odoo-bin:',
            default=current,
            description=description,
            current_value=current or None,
            error_message="La ruta es obligatoria cuando install_mode='source'.",
        )

    return prompts.ask_text(
        'Ruta absoluta a odoo-bin (vacío = auto-detectar):',
        default=current,
        description=description,
        current_value=current or None,
    )


def _ask_odoo_conf_path(existing: ClientConfig | None, *, mode: str) -> str:
    """Ask for the ``odoo.conf`` path. Optional in native, mandatory in source."""
    current = existing.odoo.odoo_conf_path if existing else ''
    description = DESCRIPTIONS[f'odoo_conf_path_{mode}']

    if mode == 'source':
        return prompts.ask_required_text(
            'Ruta absoluta a odoo.conf:',
            default=current,
            description=description,
            current_value=current or None,
            error_message="La ruta del odoo.conf es obligatoria cuando install_mode='source'.",
        )

    return prompts.ask_text(
        'Ruta absoluta a odoo.conf (opcional):',
        default=current,
        description=description,
        current_value=current or None,
    )


def _ask_python_executable(existing: ClientConfig | None, *, mode: str) -> str:
    """Ask for the Python interpreter to invoke odoo-bin with. Always optional."""
    current = existing.odoo.python_executable if existing else ''
    description = DESCRIPTIONS[f'python_executable_{mode}']
    return prompts.ask_text(
        'Ruta al intérprete Python (opcional):',
        default=current,
        description=description,
        current_value=current or None,
    )


def _ask_filestore_dir(
    existing: ClientConfig | None,
    *,
    odoo_container_name: str,
    autodetected_default: str,
) -> str:
    """Resolve ``filestore_dir`` with optional auto-detection from a container.

    Strategy when a container is provided:

    1. If ``autodetected_default`` is set (mapped from the container's
       odoo.conf), offer it as the default.
    2. Otherwise, list the container's bind-mounts/volumes so the user
       can pick the filestore one.
    3. Always allow editing the resulting path manually.
    """
    current = existing.filestore_dir if existing else ''
    default = autodetected_default or current

    if odoo_container_name and not autodetected_default:
        # No data_dir mapping: offer the user the container's mounts.
        chosen = _pick_filestore_from_container_mounts(odoo_container_name)
        if chosen:
            default = chosen

    raw = prompts.ask_required_text(
        'Directorio del filestore en el host:',
        default=default,
        description=DESCRIPTIONS['filestore_dir'],
        current_value=current or None,
    )
    # Convenience: append /filestore the first time around so the user
    # does not have to remember the convention.
    if existing is None and not raw.rstrip('/').endswith('filestore'):
        raw = os.path.join(raw, 'filestore')
    return raw


def _pick_filestore_from_container_mounts(container_name: str) -> str:
    """Let the user pick a filestore root from the container's mounts.

    Returns the host path of the selected mount, or '' if the user
    skips this step or no mounts are available.
    """
    mounts = list_container_mounts(container_name)
    if not mounts:
        return ''
    ui.info('Volúmenes/binds detectados en el contenedor Odoo:')
    pretty = [f'{m.destination}  ←  {m.host_path}  [{m.type}]' for m in mounts]
    pretty.append('<ninguno; lo escribiré a mano>')

    selected = prompts.pick_one(
        '¿Cuál de estos contiene el filestore?',
        pretty,
    )
    if not selected or selected.startswith('<ninguno'):
        return ''
    # The chosen string starts with the destination path; locate the
    # corresponding mount object to get its host_path back.
    chosen_destination = selected.split('  \u2190', 1)[0].strip()
    for m in mounts:
        if m.destination == chosen_destination:
            return m.host_path
    return ''


def _autodetect_from_docker_conf(container_name: str) -> tuple[str, str]:
    """Locate odoo.conf in a container and derive a host-side filestore path.

    Returns ``(odoo_conf_path, detected_filestore_default)``. Either or
    both can be empty strings when auto-detection failed; in that case
    the caller will fall back to listing the container's mounts.
    """
    if not container_name:
        return '', ''
    ui.working(f'Buscando odoo.conf dentro del contenedor {container_name}...')
    found = find_odoo_conf_in_container(container_name)
    if not found:
        ui.muted('No se encontró odoo.conf en rutas conocidas; continuamos sin auto-detección.')
        return '', ''
    in_container_path, conf_contents = found
    ui.success(f'odoo.conf detectado dentro del contenedor: {in_container_path}')

    data_dir = parse_data_dir_from_odoo_conf(conf_contents)
    if not data_dir:
        ui.muted('odoo.conf no declara data_dir; usaremos los volúmenes del contenedor.')
        return in_container_path, ''

    ui.info(f'data_dir declarado en odoo.conf: {data_dir}')
    host_path = map_container_path_to_host(container_name, data_dir)
    if not host_path:
        ui.warn('No se pudo mapear el data_dir a una ruta del host. Te dejaré elegir entre los volúmenes del contenedor.')
        return in_container_path, ''

    detected_filestore = os.path.join(host_path, 'filestore')
    ui.success(f'Filestore mapeado al host: {detected_filestore}')
    return in_container_path, detected_filestore


def _autodetect_filestore_from_host_conf(odoo_conf_path: str) -> str:
    """Read ``odoo_conf_path`` on the host and derive the filestore path.

    Used by ``native`` and ``source`` modes: the data_dir declared in
    odoo.conf already lives on the host, so no container mapping is
    needed. Returns an empty string when the file is not readable or
    does not declare ``data_dir``.
    """
    if not odoo_conf_path:
        return ''
    try:
        with open(odoo_conf_path, encoding='utf-8') as fh:
            contents = fh.read()
    except (FileNotFoundError, PermissionError, OSError) as err:
        ui.warn(f'No se pudo leer {odoo_conf_path}: {err}')
        return ''

    data_dir = parse_data_dir_from_odoo_conf(contents)
    if not data_dir:
        ui.muted(f'{odoo_conf_path} no declara data_dir; pediré el filestore manualmente.')
        return ''

    ui.info(f'data_dir declarado en odoo.conf: {data_dir}')
    detected_filestore = os.path.join(data_dir, 'filestore')
    ui.success(f'Filestore detectado: {detected_filestore}')
    return detected_filestore


def _preserve_upgrade(existing: ClientConfig | None) -> Upgrade:
    """Carry over the existing upgrade fields untouched (or empty defaults)."""
    if existing is None:
        return Upgrade(target='', code_subscription='', environment='')
    return existing.upgrade


def _print_summary(cfg: ClientConfig) -> None:
    ui.section('Resumen')
    ui.kv('cliente.technical_name', cfg.technical_name)
    ui.kv('cliente.filestore_dir', cfg.filestore_dir)
    ui.kv('docker.db_container', cfg.docker.db_container)
    ui.kv('odoo.install_mode', cfg.odoo.install_mode)
    if cfg.odoo.install_mode == 'docker':
        ui.kv('odoo.container_name', cfg.odoo.container_name)
    ui.kv('odoo.odoo_bin_path', cfg.odoo.odoo_bin_path or '(auto-detect)')
    if cfg.odoo.install_mode != 'docker':
        ui.kv('odoo.odoo_conf_path', cfg.odoo.odoo_conf_path or '(none)')
        ui.kv('odoo.python_executable', cfg.odoo.python_executable or '(shebang)')
    ui.divider()
