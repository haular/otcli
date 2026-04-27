"""End-to-end tests for the redesigned configuration wizard.

These tests exercise the new ordering (identity -> install_mode ->
db -> filestore), confirm that ``upgrade`` fields are no longer asked,
and verify the docker auto-detection of ``filestore_dir`` from
``odoo.conf`` + container mounts.
"""

from __future__ import annotations

from unittest.mock import patch

from otcli.domain.client_config import (
    ClientConfig,
    Database,
    Docker,
    Odoo,
    Upgrade,
)
from otcli.infrastructure import docker as docker_mod
from otcli.services import config_edit


def _silence_ui():
    """Patch all ``ui`` outputs used by the wizard so tests stay quiet."""
    return [
        patch.object(config_edit.ui, name)
        for name in ('banner', 'section', 'hint', 'info', 'success', 'warn', 'muted', 'kv', 'divider', 'working')
    ]


def _enter(*ctxs):
    return [c.__enter__() for c in ctxs], ctxs


def _exit_all(ctxs):
    for c in ctxs:
        c.__exit__(None, None, None)


def test_wizard_does_not_ask_for_upgrade_fields() -> None:
    """Smoke-test: the new wizard never invokes upgrade-related prompts.

    We assert that ``upgrade.target`` / ``code_subscription`` /
    ``environment`` come back empty strings (the default) for a brand-new
    client, proving they were not prompted.
    """
    silencers = _silence_ui()
    _, ctxs = _enter(*silencers)
    try:
        with (
            # ask_required_text is called for: technical_name, odoo-bin, odoo.conf, filestore.
            patch.object(
                config_edit.prompts,
                'ask_required_text',
                side_effect=['acme', '/x/odoo-bin', '/x/odoo.conf', '/srv/odoo/filestore'],
            ),
            # install_mode pick (we go down the source branch).
            patch.object(config_edit.prompts, 'pick_one', return_value='source'),
            # python_executable is the only ask_text call in source mode.
            patch.object(config_edit.prompts, 'ask_text', side_effect=['/usr/bin/python3']),
            patch.object(config_edit, '_handle_docker_container_selection', return_value='db_container'),
        ):
            cfg = config_edit.edit_configuration_interactive(existing=None)
    finally:
        _exit_all(ctxs)

    assert cfg.technical_name == 'acme'
    assert cfg.upgrade.target == ''
    assert cfg.upgrade.code_subscription == ''
    assert cfg.upgrade.environment == ''


def test_wizard_preserves_existing_upgrade_block() -> None:
    """When editing an existing client, upgrade fields must round-trip."""
    existing = ClientConfig(
        technical_name='acme',
        filestore_dir='/srv/filestore',
        database=Database(db_name='acme'),
        docker=Docker(db_container='db'),
        odoo=Odoo(install_mode='native', odoo_bin_path='/usr/bin/odoo'),
        upgrade=Upgrade(target='18.0', code_subscription='M1234', environment='test'),
    )

    silencers = _silence_ui()
    _, ctxs = _enter(*silencers)
    try:
        with (
            patch.object(
                config_edit.prompts,
                'ask_required_text',
                side_effect=['acme', '/srv/filestore'],
            ),
            patch.object(config_edit.prompts, 'pick_one', return_value='native'),
            patch.object(
                config_edit.prompts,
                'ask_text',
                side_effect=['', '', ''],  # bin (auto), conf (none), python (shebang)
            ),
            patch.object(
                config_edit,
                '_handle_docker_container_selection',
                return_value='db',
            ),
        ):
            cfg = config_edit.edit_configuration_interactive(existing=existing)
    finally:
        _exit_all(ctxs)

    assert cfg.upgrade.target == '18.0'
    assert cfg.upgrade.code_subscription == 'M1234'
    assert cfg.upgrade.environment == 'test'


def test_wizard_docker_autodetects_filestore_from_odoo_conf() -> None:
    """When install_mode=docker and odoo.conf carries a data_dir, the
    wizard must pre-fill filestore_dir with the host-mapped path."""
    silencers = _silence_ui()
    _, ctxs = _enter(*silencers)

    captured = {}

    def sequencer():
        seq = iter(['acme', '/srv/odoo/data/filestore'])

        def _impl(prompt, *, default='', description=None, current_value=None, error_message=''):
            captured.setdefault('defaults', []).append(default)
            return next(seq)

        return _impl

    try:
        with (
            patch.object(config_edit.prompts, 'ask_required_text', side_effect=sequencer()),
            # install_mode -> docker; subsequent pick_one calls (e.g. mounts) won't happen
            # because data_dir auto-detect succeeds.
            patch.object(config_edit.prompts, 'pick_one', return_value='docker'),
            # odoo_bin_path inside container -> empty (auto)
            patch.object(config_edit.prompts, 'ask_text', return_value=''),
            # Both container pickers return predictable names.
            patch.object(
                config_edit,
                '_handle_docker_container_selection',
                side_effect=['odoo_container', 'db_container'],
            ),
            # Auto-detection helpers
            patch.object(
                config_edit,
                'find_odoo_conf_in_container',
                return_value=('/etc/odoo/odoo.conf', 'data_dir = /var/lib/odoo'),
            ),
            patch.object(config_edit, 'parse_data_dir_from_odoo_conf', return_value='/var/lib/odoo'),
            patch.object(config_edit, 'map_container_path_to_host', return_value='/srv/odoo/data'),
        ):
            cfg = config_edit.edit_configuration_interactive(existing=None)
    finally:
        _exit_all(ctxs)

    # Filestore prompt should have been pre-filled with the auto-detected path.
    assert '/srv/odoo/data/filestore' in captured['defaults']
    assert cfg.odoo.install_mode == 'docker'
    assert cfg.odoo.container_name == 'odoo_container'
    assert cfg.docker.db_container == 'db_container'
    assert cfg.odoo.odoo_conf_path == '/etc/odoo/odoo.conf'


def test_wizard_native_autodetects_filestore_from_host_odoo_conf(tmp_path) -> None:
    """When install_mode=native and the user provides an odoo.conf path,
    the wizard reads the file from the host, parses ``data_dir`` and
    pre-fills filestore_dir without prompting."""
    conf_path = tmp_path / 'odoo.conf'
    conf_path.write_text('[options]\ndata_dir = /var/lib/odoo\nadmin_passwd = x\n', encoding='utf-8')

    silencers = _silence_ui()
    _, ctxs = _enter(*silencers)

    captured: dict[str, list[str]] = {}

    def sequencer():
        # Order: technical_name -> filestore_dir
        seq = iter(['acme', '/var/lib/odoo/filestore'])

        def _impl(prompt, *, default='', description=None, current_value=None, error_message=''):
            captured.setdefault('defaults', []).append(default)
            return next(seq)

        return _impl

    try:
        with (
            patch.object(config_edit.prompts, 'ask_required_text', side_effect=sequencer()),
            patch.object(config_edit.prompts, 'pick_one', return_value='native'),
            # ask_text is called for: odoo-bin (auto), odoo.conf, python_executable
            patch.object(
                config_edit.prompts,
                'ask_text',
                side_effect=['', str(conf_path), ''],
            ),
            patch.object(config_edit, '_handle_docker_container_selection', return_value='db_container'),
        ):
            cfg = config_edit.edit_configuration_interactive(existing=None)
    finally:
        _exit_all(ctxs)

    # The default offered for filestore_dir must be the auto-detected
    # one ("/var/lib/odoo/filestore"), not empty.
    assert '/var/lib/odoo/filestore' in captured['defaults']
    assert cfg.odoo.install_mode == 'native'
    assert cfg.odoo.odoo_conf_path == str(conf_path)
    assert cfg.filestore_dir == '/var/lib/odoo/filestore'


def test_wizard_source_autodetects_filestore_from_host_odoo_conf(tmp_path) -> None:
    """Same auto-detection in source mode."""
    conf_path = tmp_path / 'odoo.conf'
    conf_path.write_text('data_dir=/srv/odoo/data\n', encoding='utf-8')

    silencers = _silence_ui()
    _, ctxs = _enter(*silencers)

    captured: dict[str, list[str]] = {}

    def sequencer():
        # Order: technical_name -> odoo-bin -> odoo.conf -> filestore_dir
        seq = iter(['acme', '/x/odoo-bin', str(conf_path), '/srv/odoo/data/filestore'])

        def _impl(prompt, *, default='', description=None, current_value=None, error_message=''):
            captured.setdefault('defaults', []).append(default)
            return next(seq)

        return _impl

    try:
        with (
            patch.object(config_edit.prompts, 'ask_required_text', side_effect=sequencer()),
            patch.object(config_edit.prompts, 'pick_one', return_value='source'),
            patch.object(config_edit.prompts, 'ask_text', return_value=''),
            patch.object(config_edit, '_handle_docker_container_selection', return_value='db_container'),
        ):
            cfg = config_edit.edit_configuration_interactive(existing=None)
    finally:
        _exit_all(ctxs)

    assert '/srv/odoo/data/filestore' in captured['defaults']
    assert cfg.odoo.install_mode == 'source'
    assert cfg.filestore_dir == '/srv/odoo/data/filestore'


def test_wizard_native_handles_unreadable_odoo_conf(tmp_path) -> None:
    """If odoo.conf cannot be opened we degrade gracefully (no auto-detect)."""
    silencers = _silence_ui()
    _, ctxs = _enter(*silencers)

    captured: dict[str, list[str]] = {}

    def sequencer():
        seq = iter(['acme', '/manual/path/filestore'])

        def _impl(prompt, *, default='', description=None, current_value=None, error_message=''):
            captured.setdefault('defaults', []).append(default)
            return next(seq)

        return _impl

    missing_conf = str(tmp_path / 'does_not_exist.conf')

    try:
        with (
            patch.object(config_edit.prompts, 'ask_required_text', side_effect=sequencer()),
            patch.object(config_edit.prompts, 'pick_one', return_value='native'),
            # odoo-bin auto, odoo.conf -> a path that does not exist, python_exec empty
            patch.object(config_edit.prompts, 'ask_text', side_effect=['', missing_conf, '']),
            patch.object(config_edit, '_handle_docker_container_selection', return_value='db'),
        ):
            cfg = config_edit.edit_configuration_interactive(existing=None)
    finally:
        _exit_all(ctxs)

    # Default offered must NOT be a derived /filestore path; the wizard
    # falls back to whatever the user types ('/manual/path/filestore').
    # The pre-fill default for the filestore prompt should be empty.
    filestore_default_offered = captured['defaults'][1]
    assert filestore_default_offered == ''
    assert cfg.filestore_dir == '/manual/path/filestore'


def test_wizard_docker_falls_back_to_mounts_when_no_data_dir() -> None:
    """When data_dir cannot be auto-detected, the wizard offers the
    container's mounts so the user can pick the filestore location."""
    silencers = _silence_ui()
    _, ctxs = _enter(*silencers)

    fake_mounts = [
        docker_mod.ContainerMount(
            type='bind',
            source='/srv/odoo/filestore',
            destination='/var/lib/odoo',
            host_path='/srv/odoo/filestore',
        )
    ]

    try:
        with (
            patch.object(
                config_edit.prompts,
                'ask_required_text',
                side_effect=['acme', '/srv/odoo/filestore'],
            ),
            # First pick_one: install_mode='docker'; second pick_one (mounts): the bind.
            patch.object(
                config_edit.prompts,
                'pick_one',
                side_effect=[
                    'docker',  # install mode
                    '/var/lib/odoo  \u2190  /srv/odoo/filestore  [bind]',  # mount selection
                ],
            ),
            patch.object(config_edit.prompts, 'ask_text', return_value=''),  # odoo-bin auto
            patch.object(
                config_edit,
                '_handle_docker_container_selection',
                side_effect=['odoo_container', 'db_container'],
            ),
            # No odoo.conf found in the container.
            patch.object(config_edit, 'find_odoo_conf_in_container', return_value=None),
            patch.object(config_edit, 'list_container_mounts', return_value=fake_mounts),
        ):
            cfg = config_edit.edit_configuration_interactive(existing=None)
    finally:
        _exit_all(ctxs)

    assert cfg.odoo.install_mode == 'docker'
    assert cfg.filestore_dir == '/srv/odoo/filestore'
