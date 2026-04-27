"""Tests for docker mount inspection and odoo.conf parsing helpers.

We patch ``subprocess.run`` so the tests stay hermetic and never invoke
the real docker daemon.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from otcli.infrastructure import docker as docker_mod


def _fake_subprocess(stdout: str = '', returncode: int = 0, stderr: str = '') -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


# --- list_container_mounts ----------------------------------------------


def test_list_container_mounts_parses_binds_and_volumes() -> None:
    payload = [
        {
            'Mounts': [
                {
                    'Type': 'bind',
                    'Source': '/srv/odoo/data',
                    'Destination': '/var/lib/odoo',
                },
                {
                    'Type': 'volume',
                    'Name': 'odoo-data',
                    'Source': '/var/lib/docker/volumes/odoo-data/_data',
                    'Destination': '/opt/odoo/data',
                },
            ]
        }
    ]
    with patch.object(docker_mod.subprocess, 'run', return_value=_fake_subprocess(json.dumps(payload))):
        mounts = docker_mod.list_container_mounts('odoo')

    assert len(mounts) == 2
    assert mounts[0].type == 'bind'
    assert mounts[0].host_path == '/srv/odoo/data'
    assert mounts[0].source == '/srv/odoo/data'
    assert mounts[1].type == 'volume'
    assert mounts[1].source == 'odoo-data'  # for volumes, source is the name
    assert mounts[1].host_path == '/var/lib/docker/volumes/odoo-data/_data'


def test_list_container_mounts_returns_empty_on_inspect_failure() -> None:
    with patch.object(docker_mod.subprocess, 'run', return_value=_fake_subprocess(returncode=1, stderr='no container')):
        assert docker_mod.list_container_mounts('nope') == []


def test_list_container_mounts_handles_missing_docker() -> None:
    with patch.object(docker_mod.subprocess, 'run', side_effect=FileNotFoundError):
        assert docker_mod.list_container_mounts('any') == []


# --- read_file_from_container -------------------------------------------


def test_read_file_from_container_returns_contents() -> None:
    with patch.object(docker_mod.subprocess, 'run', return_value=_fake_subprocess('data_dir = /var/lib/odoo\n')):
        out = docker_mod.read_file_from_container('odoo', '/etc/odoo/odoo.conf')
    assert out is not None
    assert 'data_dir' in out


def test_read_file_from_container_returns_none_on_failure() -> None:
    with patch.object(docker_mod.subprocess, 'run', return_value=_fake_subprocess(returncode=1, stderr='no such file')):
        assert docker_mod.read_file_from_container('odoo', '/missing') is None


# --- find_odoo_conf_in_container ----------------------------------------


def test_find_odoo_conf_in_container_finds_first_match(monkeypatch) -> None:
    """The helper probes a list of well-known paths; first hit wins."""
    answers = {
        '/etc/odoo/odoo.conf': None,  # not found
        '/etc/odoo.conf': 'data_dir = /var/lib/odoo',  # found
        '/etc/odoo/openerp-server.conf': 'should_not_reach',
    }

    def fake_read(_container: str, path: str) -> str | None:
        return answers[path]

    monkeypatch.setattr(docker_mod, 'read_file_from_container', fake_read)
    found = docker_mod.find_odoo_conf_in_container('odoo')
    assert found == ('/etc/odoo.conf', 'data_dir = /var/lib/odoo')


def test_find_odoo_conf_in_container_returns_none_if_not_found(monkeypatch) -> None:
    monkeypatch.setattr(docker_mod, 'read_file_from_container', lambda *_: None)
    assert docker_mod.find_odoo_conf_in_container('odoo') is None


# --- parse_data_dir_from_odoo_conf --------------------------------------


def test_parse_data_dir_from_odoo_conf_extracts_value() -> None:
    contents = '\n'.join(
        [
            '[options]',
            '; comment',
            'addons_path = /mnt/extra-addons',
            'data_dir = /var/lib/odoo',
            'admin_passwd = secret',
        ]
    )
    assert docker_mod.parse_data_dir_from_odoo_conf(contents) == '/var/lib/odoo'


def test_parse_data_dir_from_odoo_conf_ignores_comments() -> None:
    contents = '\n'.join(
        [
            '# data_dir = /should/not/read',
            '; data_dir = /also/not',
            'data_dir = /actual/dir',
        ]
    )
    assert docker_mod.parse_data_dir_from_odoo_conf(contents) == '/actual/dir'


def test_parse_data_dir_from_odoo_conf_returns_none_when_missing() -> None:
    assert docker_mod.parse_data_dir_from_odoo_conf('addons_path = /x') is None


# --- map_container_path_to_host -----------------------------------------


def test_map_container_path_to_host_maps_via_longest_prefix(monkeypatch) -> None:
    fake_mounts = [
        docker_mod.ContainerMount(
            type='bind',
            source='/srv/odoo/data',
            destination='/var/lib/odoo',
            host_path='/srv/odoo/data',
        ),
        docker_mod.ContainerMount(
            type='bind',
            source='/srv/odoo/sessions',
            destination='/var/lib/odoo/sessions',
            host_path='/srv/odoo/sessions',
        ),
    ]
    monkeypatch.setattr(docker_mod, 'list_container_mounts', lambda _name: fake_mounts)

    # Inside the data_dir => first mount.
    assert docker_mod.map_container_path_to_host('odoo', '/var/lib/odoo') == '/srv/odoo/data'
    # Sub-path of the longer mount => prefer the longer match.
    assert docker_mod.map_container_path_to_host('odoo', '/var/lib/odoo/sessions') == '/srv/odoo/sessions'
    # Sub-path of the shorter mount.
    assert docker_mod.map_container_path_to_host('odoo', '/var/lib/odoo/filestore') == '/srv/odoo/data/filestore'


def test_map_container_path_to_host_returns_none_when_no_match(monkeypatch) -> None:
    monkeypatch.setattr(docker_mod, 'list_container_mounts', lambda _name: [])
    assert docker_mod.map_container_path_to_host('odoo', '/anywhere') is None
