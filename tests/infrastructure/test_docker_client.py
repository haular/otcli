"""Tests for docker_client helpers.

Focuses on the ``_exec_in_container`` contract: the ``check`` flag (previously
named ``sys_exit``) must be honoured so that callers can opt-in to tolerating
non-zero exit codes (e.g. ``dropdb`` against a non-existent DB).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from otcli.domain.exceptions import ContainerNotFoundError
from otcli.infrastructure.docker import _exec_in_container


def _fake_container(exit_code: int, output: bytes = b'') -> MagicMock:
    container = MagicMock()
    container.exec_run.return_value = SimpleNamespace(exit_code=exit_code, output=output)
    return container


class TestExecInContainerCheckFlag:
    def test_success_returns_result(self) -> None:
        container = _fake_container(0, b'ok')
        result = _exec_in_container(container, 'echo ok')
        assert result.exit_code == 0

    def test_nonzero_exit_raises_by_default(self) -> None:
        container = _fake_container(1, b'boom')
        with pytest.raises(ContainerNotFoundError):
            _exec_in_container(container, 'false')

    def test_check_false_does_not_raise_on_nonzero(self) -> None:
        """The key regression: restore passes ``check=False`` for ``dropdb`` so
        that a missing DB does not abort the whole restore flow."""
        container = _fake_container(1, b'database does not exist')
        # Must not raise.
        result = _exec_in_container(container, 'dropdb db', check=False)
        assert result is not None
        assert result.exit_code == 1

    def test_exception_from_docker_is_wrapped(self) -> None:
        container = MagicMock()
        container.exec_run.side_effect = RuntimeError('docker down')
        with pytest.raises(ContainerNotFoundError):
            _exec_in_container(container, 'echo')
