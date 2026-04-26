"""Tests for the post-restore odoo-bin neutralization helper."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import NeutralizeError
from otcli.infrastructure import neutralize as neut


def _proc(returncode: int = 0, stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=['docker'], returncode=returncode, stdout=stdout, stderr=stderr)


def test_explicit_path_takes_precedence(client_dict: dict) -> None:
    client_dict['docker']['odoo_bin_path'] = '/custom/odoo-bin'
    cfg = ClientConfig.from_dict(client_dict)

    with patch.object(neut, '_docker_exec') as mock_exec:
        # First call: ``test -x /custom/odoo-bin`` succeeds.
        # Second call: actual neutralize.
        mock_exec.side_effect = [_proc(0), _proc(0)]
        neut.neutralize_database(cfg)

    # Ensure the explicit path was passed to neutralize and 'which' / fallbacks
    # were never probed.
    calls = mock_exec.call_args_list
    assert len(calls) == 2
    assert calls[0].args == (cfg.docker.odoo_container, ['test', '-x', '/custom/odoo-bin'])
    assert calls[1].args[1] == ['/custom/odoo-bin', 'neutralize', '-d', 'acme']


def test_explicit_path_not_executable_raises(client_dict: dict) -> None:
    client_dict['docker']['odoo_bin_path'] = '/nope/odoo-bin'
    cfg = ClientConfig.from_dict(client_dict)

    with (
        patch.object(neut, '_docker_exec', return_value=_proc(returncode=1)),
        pytest.raises(NeutralizeError, match='not executable'),
    ):
        neut.neutralize_database(cfg)


def test_auto_detect_uses_which_first(client_dict: dict) -> None:
    cfg = ClientConfig.from_dict(client_dict)

    with patch.object(neut, '_docker_exec') as mock_exec:
        # which odoo-bin -> /usr/bin/odoo-bin, then neutralize succeeds.
        mock_exec.side_effect = [
            _proc(returncode=0, stdout='/usr/bin/odoo-bin\n'),
            _proc(returncode=0),
        ]
        neut.neutralize_database(cfg)

    # First call is `which`; we never probe the static fallbacks.
    first_call_argv = mock_exec.call_args_list[0].args[1]
    assert first_call_argv == ['which', 'odoo-bin']
    # Second call is the actual neutralize using the resolved path.
    second_call_argv = mock_exec.call_args_list[1].args[1]
    assert second_call_argv == ['/usr/bin/odoo-bin', 'neutralize', '-d', 'acme']


def test_auto_detect_falls_back_through_candidates(client_dict: dict) -> None:
    cfg = ClientConfig.from_dict(client_dict)

    with patch.object(neut, '_docker_exec') as mock_exec:
        # which fails, /usr/bin/odoo-bin fails, /mnt/odoo/odoo-bin works,
        # then the actual neutralize succeeds.
        mock_exec.side_effect = [
            _proc(returncode=1),  # which odoo-bin
            _proc(returncode=1),  # test -x /usr/bin/odoo-bin
            _proc(returncode=0),  # test -x /mnt/odoo/odoo-bin
            _proc(returncode=0),  # neutralize
        ]
        neut.neutralize_database(cfg)

    last_call_argv = mock_exec.call_args_list[-1].args[1]
    assert last_call_argv[0] == '/mnt/odoo/odoo-bin'


def test_auto_detect_all_fail_raises(client_dict: dict) -> None:
    cfg = ClientConfig.from_dict(client_dict)

    with (
        patch.object(neut, '_docker_exec', return_value=_proc(returncode=1)),
        pytest.raises(NeutralizeError, match='odoo-bin not found'),
    ):
        neut.neutralize_database(cfg)


def test_neutralize_command_failure_propagates_stderr(client_dict: dict) -> None:
    client_dict['docker']['odoo_bin_path'] = '/usr/bin/odoo-bin'
    cfg = ClientConfig.from_dict(client_dict)

    with patch.object(neut, '_docker_exec') as mock_exec:
        mock_exec.side_effect = [
            _proc(returncode=0),  # test -x ok
            _proc(returncode=1, stderr='ERROR: addons-path missing\n'),  # neutralize
        ]
        with pytest.raises(NeutralizeError, match='addons-path missing'):
            neut.neutralize_database(cfg)


def test_empty_odoo_container_raises(client_dict: dict) -> None:
    client_dict['docker']['odoo_container'] = ''
    cfg = ClientConfig.from_dict(client_dict)

    with pytest.raises(NeutralizeError, match='odoo_container'):
        neut.neutralize_database(cfg)


def test_db_name_defaults_to_technical_name(client_dict: dict) -> None:
    """When database.db_name is empty, neutralize uses client.technical_name."""
    client_dict['client']['technical_name'] = 'beta'
    client_dict['database']['db_name'] = ''
    client_dict['docker']['odoo_bin_path'] = '/usr/bin/odoo-bin'
    cfg = ClientConfig.from_dict(client_dict)

    with patch.object(neut, '_docker_exec') as mock_exec:
        mock_exec.side_effect = [_proc(0), _proc(0)]
        neut.neutralize_database(cfg)

    neutralize_call_argv = mock_exec.call_args_list[-1].args[1]
    assert neutralize_call_argv == ['/usr/bin/odoo-bin', 'neutralize', '-d', 'beta']
