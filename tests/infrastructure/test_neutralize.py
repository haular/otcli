"""Tests for the post-restore odoo-bin neutralization helper.

Covers all three Odoo deployment topologies:

* ``install_mode='docker'``: command runs via ``docker exec``; odoo-bin
  is auto-detected inside the container.
* ``install_mode='native'``: command runs on the host via ``subprocess``;
  odoo-bin is auto-detected via ``shutil.which`` then a fallback path.
* ``install_mode='source'``: command runs on the host; ``odoo_bin_path``
  is required and validated against the host filesystem.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import NeutralizeError
from otcli.infrastructure import neutralize as neut


def _proc(returncode: int = 0, stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=['cmd'], returncode=returncode, stdout=stdout, stderr=stderr)


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\nexit 0\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


# =========================================================================
# install_mode='docker'
# =========================================================================


class TestDockerMode:
    def test_explicit_path_takes_precedence(self, client_dict: dict) -> None:
        client_dict['odoo']['odoo_bin_path'] = '/custom/odoo-bin'
        cfg = ClientConfig.from_dict(client_dict)

        with patch.object(neut, '_docker_exec') as mock_exec:
            mock_exec.side_effect = [_proc(0), _proc(0)]  # test -x, then neutralize
            neut.neutralize_database(cfg)

        calls = mock_exec.call_args_list
        assert len(calls) == 2
        assert calls[0].args == (cfg.odoo.container_name, ['test', '-x', '/custom/odoo-bin'])
        assert calls[1].args[1] == ['/custom/odoo-bin', 'neutralize', '-d', 'acme']

    def test_explicit_path_not_executable_raises(self, client_dict: dict) -> None:
        client_dict['odoo']['odoo_bin_path'] = '/nope/odoo-bin'
        cfg = ClientConfig.from_dict(client_dict)

        with (
            patch.object(neut, '_docker_exec', return_value=_proc(returncode=1)),
            pytest.raises(NeutralizeError, match='not executable'),
        ):
            neut.neutralize_database(cfg)

    def test_auto_detect_uses_which_first(self, client_dict: dict) -> None:
        cfg = ClientConfig.from_dict(client_dict)

        with patch.object(neut, '_docker_exec') as mock_exec:
            mock_exec.side_effect = [
                _proc(returncode=0, stdout='/usr/bin/odoo-bin\n'),  # which
                _proc(returncode=0),  # neutralize
            ]
            neut.neutralize_database(cfg)

        first_call_argv = mock_exec.call_args_list[0].args[1]
        assert first_call_argv == ['which', 'odoo-bin']
        last_call_argv = mock_exec.call_args_list[-1].args[1]
        assert last_call_argv == ['/usr/bin/odoo-bin', 'neutralize', '-d', 'acme']

    def test_auto_detect_falls_back_through_candidates(self, client_dict: dict) -> None:
        cfg = ClientConfig.from_dict(client_dict)

        with patch.object(neut, '_docker_exec') as mock_exec:
            mock_exec.side_effect = [
                _proc(returncode=1),  # which
                _proc(returncode=1),  # /usr/bin/odoo-bin
                _proc(returncode=0),  # /mnt/odoo/odoo-bin  ← match
                _proc(returncode=0),  # neutralize
            ]
            neut.neutralize_database(cfg)

        last_call_argv = mock_exec.call_args_list[-1].args[1]
        assert last_call_argv[0] == '/mnt/odoo/odoo-bin'

    def test_auto_detect_all_fail_raises(self, client_dict: dict) -> None:
        cfg = ClientConfig.from_dict(client_dict)

        with (
            patch.object(neut, '_docker_exec', return_value=_proc(returncode=1)),
            pytest.raises(NeutralizeError, match='odoo-bin not found'),
        ):
            neut.neutralize_database(cfg)

    def test_command_failure_propagates_stderr(self, client_dict: dict) -> None:
        client_dict['odoo']['odoo_bin_path'] = '/usr/bin/odoo-bin'
        cfg = ClientConfig.from_dict(client_dict)

        with patch.object(neut, '_docker_exec') as mock_exec:
            mock_exec.side_effect = [
                _proc(returncode=0),  # test -x ok
                _proc(returncode=1, stderr='ERROR: addons-path missing\n'),
            ]
            with pytest.raises(NeutralizeError, match='addons-path missing'):
                neut.neutralize_database(cfg)

    def test_empty_container_name_raises(self, client_dict: dict) -> None:
        # Build a config with empty container_name; we have to bypass
        # ClientConfig.from_dict's validation since it would reject this.
        cfg = ClientConfig.from_dict(client_dict)
        cfg_no_container = cfg.__class__(
            technical_name=cfg.technical_name,
            filestore_dir=cfg.filestore_dir,
            database=cfg.database,
            docker=cfg.docker,
            odoo=cfg.odoo.__class__(
                install_mode='docker',
                container_name='',
                odoo_bin_path=cfg.odoo.odoo_bin_path,
            ),
            upgrade=cfg.upgrade,
        )

        with pytest.raises(NeutralizeError, match='container_name'):
            neut.neutralize_database(cfg_no_container)

    def test_db_name_defaults_to_technical_name(self, client_dict: dict) -> None:
        client_dict['client']['technical_name'] = 'beta'
        client_dict['database']['db_name'] = ''
        client_dict['odoo']['odoo_bin_path'] = '/usr/bin/odoo-bin'
        cfg = ClientConfig.from_dict(client_dict)

        with patch.object(neut, '_docker_exec') as mock_exec:
            mock_exec.side_effect = [_proc(0), _proc(0)]
            neut.neutralize_database(cfg)

        last_call_argv = mock_exec.call_args_list[-1].args[1]
        assert last_call_argv == ['/usr/bin/odoo-bin', 'neutralize', '-d', 'beta']

    def test_docker_ignores_odoo_conf_path(self, client_dict: dict) -> None:
        """Docker mode never forwards odoo_conf_path even if set:
        the container has its own embedded configuration."""
        client_dict['odoo']['odoo_bin_path'] = '/usr/bin/odoo-bin'
        client_dict['odoo']['odoo_conf_path'] = '/some/conf/from/host.conf'
        cfg = ClientConfig.from_dict(client_dict)

        with patch.object(neut, '_docker_exec') as mock_exec:
            mock_exec.side_effect = [_proc(0), _proc(0)]
            neut.neutralize_database(cfg)

        last_call_argv = mock_exec.call_args_list[-1].args[1]
        assert last_call_argv == ['/usr/bin/odoo-bin', 'neutralize', '-d', 'acme']
        assert '-c' not in last_call_argv


# =========================================================================
# install_mode='native'
# =========================================================================


class TestNativeMode:
    def test_auto_detect_via_which(self, client_dict: dict) -> None:
        client_dict['odoo']['install_mode'] = 'native'
        client_dict['odoo']['container_name'] = ''
        client_dict['odoo']['odoo_bin_path'] = ''
        cfg = ClientConfig.from_dict(client_dict)

        with (
            patch.object(neut.shutil, 'which', return_value='/usr/bin/odoo-bin'),
            patch.object(neut, '_host_exec', return_value=_proc(0)) as mock_host,
        ):
            neut.neutralize_database(cfg)

        mock_host.assert_called_once()
        argv = mock_host.call_args.args[0]
        assert argv == ['/usr/bin/odoo-bin', 'neutralize', '-d', 'acme']

    def test_auto_detect_falls_back_to_usr_bin(self, client_dict: dict, tmp_path: Path) -> None:
        client_dict['odoo']['install_mode'] = 'native'
        client_dict['odoo']['container_name'] = ''
        client_dict['odoo']['odoo_bin_path'] = ''
        cfg = ClientConfig.from_dict(client_dict)

        # which returns nothing; let _is_executable claim /usr/bin/odoo-bin exists.
        with (
            patch.object(neut.shutil, 'which', return_value=None),
            patch.object(neut, '_is_executable', return_value=True),
            patch.object(neut.Path, 'is_file', return_value=True),
            patch.object(neut, '_host_exec', return_value=_proc(0)) as mock_host,
        ):
            neut.neutralize_database(cfg)

        argv = mock_host.call_args.args[0]
        assert argv[0] == '/usr/bin/odoo-bin'

    def test_explicit_path_validated_against_host(self, client_dict: dict, tmp_path: Path) -> None:
        odoo_bin = _make_executable(tmp_path / 'odoo-bin')
        client_dict['odoo']['install_mode'] = 'native'
        client_dict['odoo']['container_name'] = ''
        client_dict['odoo']['odoo_bin_path'] = str(odoo_bin)
        cfg = ClientConfig.from_dict(client_dict)

        with patch.object(neut, '_host_exec', return_value=_proc(0)) as mock_host:
            neut.neutralize_database(cfg)

        argv = mock_host.call_args.args[0]
        assert argv == [str(odoo_bin), 'neutralize', '-d', 'acme']

    def test_explicit_path_missing_raises(self, client_dict: dict, tmp_path: Path) -> None:
        client_dict['odoo']['install_mode'] = 'native'
        client_dict['odoo']['container_name'] = ''
        client_dict['odoo']['odoo_bin_path'] = str(tmp_path / 'does-not-exist')
        cfg = ClientConfig.from_dict(client_dict)

        with pytest.raises(NeutralizeError, match='not an executable file'):
            neut.neutralize_database(cfg)

    def test_explicit_path_not_executable_raises(self, client_dict: dict, tmp_path: Path) -> None:
        not_x = tmp_path / 'odoo-bin'
        not_x.write_text('#!/bin/sh\n')
        # No execute bit.
        not_x.chmod(0o644)
        client_dict['odoo']['install_mode'] = 'native'
        client_dict['odoo']['container_name'] = ''
        client_dict['odoo']['odoo_bin_path'] = str(not_x)
        cfg = ClientConfig.from_dict(client_dict)

        with pytest.raises(NeutralizeError, match='not an executable file'):
            neut.neutralize_database(cfg)

    def test_no_odoo_bin_anywhere_raises(self, client_dict: dict) -> None:
        client_dict['odoo']['install_mode'] = 'native'
        client_dict['odoo']['container_name'] = ''
        client_dict['odoo']['odoo_bin_path'] = ''
        cfg = ClientConfig.from_dict(client_dict)

        with (
            patch.object(neut.shutil, 'which', return_value=None),
            patch.object(neut, '_is_executable', return_value=False),
            pytest.raises(NeutralizeError, match='odoo-bin not found on host'),
        ):
            neut.neutralize_database(cfg)

    def test_native_without_conf_does_not_pass_minus_c(self, client_dict: dict) -> None:
        """Without odoo_conf_path, native mode invokes odoo-bin directly."""
        client_dict['odoo']['install_mode'] = 'native'
        client_dict['odoo']['container_name'] = ''
        client_dict['odoo']['odoo_bin_path'] = ''
        client_dict['odoo']['odoo_conf_path'] = ''
        cfg = ClientConfig.from_dict(client_dict)

        with (
            patch.object(neut.shutil, 'which', return_value='/usr/bin/odoo-bin'),
            patch.object(neut, '_host_exec', return_value=_proc(0)) as mock_host,
        ):
            neut.neutralize_database(cfg)

        argv = mock_host.call_args.args[0]
        assert argv == ['/usr/bin/odoo-bin', 'neutralize', '-d', 'acme']
        assert '-c' not in argv

    def test_native_with_conf_passes_minus_c(self, client_dict: dict) -> None:
        client_dict['odoo']['install_mode'] = 'native'
        client_dict['odoo']['container_name'] = ''
        client_dict['odoo']['odoo_bin_path'] = ''
        client_dict['odoo']['odoo_conf_path'] = '/etc/odoo/custom.conf'
        cfg = ClientConfig.from_dict(client_dict)

        with (
            patch.object(neut.shutil, 'which', return_value='/usr/bin/odoo-bin'),
            patch.object(neut, '_host_exec', return_value=_proc(0)) as mock_host,
        ):
            neut.neutralize_database(cfg)

        argv = mock_host.call_args.args[0]
        assert argv == [
            '/usr/bin/odoo-bin',
            '-c',
            '/etc/odoo/custom.conf',
            'neutralize',
            '-d',
            'acme',
        ]


# =========================================================================
# install_mode='source'
# =========================================================================


class TestSourceMode:
    @staticmethod
    def _set_source(client_dict: dict, *, odoo_bin: str, odoo_conf: str = '/tmp/x.conf') -> None:
        client_dict['odoo']['install_mode'] = 'source'
        client_dict['odoo']['container_name'] = ''
        client_dict['odoo']['odoo_bin_path'] = odoo_bin
        client_dict['odoo']['odoo_conf_path'] = odoo_conf

    def test_explicit_path_runs_on_host_with_conf(self, client_dict: dict, tmp_path: Path) -> None:
        odoo_bin = _make_executable(tmp_path / 'odoo' / 'odoo-bin')
        odoo_conf = '/home/user/projects/acme/odoo.conf'
        self._set_source(client_dict, odoo_bin=str(odoo_bin), odoo_conf=odoo_conf)
        cfg = ClientConfig.from_dict(client_dict)

        with patch.object(neut, '_host_exec', return_value=_proc(0)) as mock_host:
            neut.neutralize_database(cfg)

        argv = mock_host.call_args.args[0]
        # -c <conf> must precede 'neutralize -d <db>'
        assert argv == [str(odoo_bin), '-c', odoo_conf, 'neutralize', '-d', 'acme']

    def test_missing_odoo_bin_path_rejected_by_schema(self, client_dict: dict) -> None:
        """When install_mode='source' and odoo_bin_path is empty,
        ClientConfig.from_dict already rejects the input."""
        from otcli.domain.exceptions import ClientConfigError

        self._set_source(client_dict, odoo_bin='', odoo_conf='/tmp/x.conf')
        with pytest.raises(ClientConfigError, match='odoo_bin_path is required'):
            ClientConfig.from_dict(client_dict)

    def test_missing_odoo_conf_path_rejected_by_schema(self, client_dict: dict) -> None:
        """When install_mode='source' and odoo_conf_path is empty,
        ClientConfig.from_dict already rejects the input."""
        from otcli.domain.exceptions import ClientConfigError

        self._set_source(client_dict, odoo_bin='/home/user/odoo-bin', odoo_conf='')
        with pytest.raises(ClientConfigError, match='odoo_conf_path is required'):
            ClientConfig.from_dict(client_dict)

    def test_explicit_path_invalid_raises_at_runtime(self, client_dict: dict, tmp_path: Path) -> None:
        self._set_source(client_dict, odoo_bin=str(tmp_path / 'does-not-exist'))
        cfg = ClientConfig.from_dict(client_dict)

        with pytest.raises(NeutralizeError, match='not an executable file'):
            neut.neutralize_database(cfg)

    def test_command_failure_propagates_stderr(self, client_dict: dict, tmp_path: Path) -> None:
        odoo_bin = _make_executable(tmp_path / 'odoo-bin')
        self._set_source(client_dict, odoo_bin=str(odoo_bin))
        cfg = ClientConfig.from_dict(client_dict)

        with (
            patch.object(
                neut,
                '_host_exec',
                return_value=_proc(returncode=1, stderr='oops something failed'),
            ),
            pytest.raises(NeutralizeError, match='oops something failed'),
        ):
            neut.neutralize_database(cfg)


# =========================================================================
# Cross-mode invariants
# =========================================================================


def test_unknown_install_mode_raises_at_runtime(client_dict: dict) -> None:
    """The schema validates install_mode at load time; this test guards the
    runtime defensive branch in case someone constructs a ClientConfig
    bypassing from_dict."""
    cfg = ClientConfig.from_dict(client_dict)
    # Forge an invalid mode by replacing the frozen Odoo dataclass in place.
    bad_odoo = cfg.odoo.__class__.__new__(cfg.odoo.__class__)
    object.__setattr__(bad_odoo, 'install_mode', 'kubernetes')
    object.__setattr__(bad_odoo, 'container_name', '')
    object.__setattr__(bad_odoo, 'odoo_bin_path', '')
    bad_cfg = cfg.__class__.__new__(cfg.__class__)
    for field_name in (
        'technical_name',
        'filestore_dir',
        'database',
        'docker',
        'upgrade',
    ):
        object.__setattr__(bad_cfg, field_name, getattr(cfg, field_name))
    object.__setattr__(bad_cfg, 'odoo', bad_odoo)

    # The dispatcher hits the docker container guard first because the
    # 'kubernetes' mode is not handled \u2014 we expect NeutralizeError or
    # any subclass to surface.
    with pytest.raises(NeutralizeError):
        neut.neutralize_database(bad_cfg)


# Silence unused import warning when running as standalone.
assert os is not None
