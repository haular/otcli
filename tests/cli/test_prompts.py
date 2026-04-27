"""Tests for the interactive prompt helpers in ``otcli.cli.prompts``.

We stub out the ``questionary`` calls so the tests run in a non-tty
environment (CI) without spawning the prompt-toolkit event loop.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from otcli.cli import prompts
from otcli.domain.exceptions import OdooCLIError


class _FakeQuestion:
    def __init__(self, answer: Any):
        self._answer = answer

    def ask(self) -> Any:
        return self._answer


def test_pick_one_returns_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts.questionary, 'select', MagicMock(return_value=_FakeQuestion('beta')))
    assert prompts.pick_one('Pick:', ['alpha', 'beta', 'gamma']) == 'beta'


def test_pick_one_empty_items_returns_none() -> None:
    assert prompts.pick_one('Pick:', [], allow_create=False) is None


def test_pick_one_with_allow_create_signals_create(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        prompts.questionary,
        'select',
        MagicMock(return_value=_FakeQuestion(prompts.CREATE_NEW_SENTINEL)),
    )
    assert prompts.pick_one('Pick:', ['x'], allow_create=True) is None


def test_pick_one_aborted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts.questionary, 'select', MagicMock(return_value=_FakeQuestion(None)))
    with pytest.raises(OdooCLIError, match='cancelada'):
        prompts.pick_one('Pick:', ['x'])


def test_ask_text_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts.questionary, 'text', MagicMock(return_value=_FakeQuestion('hello')))
    monkeypatch.setattr(prompts.questionary, 'print', lambda *a, **k: None)
    assert prompts.ask_text('Q:', default='') == 'hello'


def test_ask_secret_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts.questionary, 'password', MagicMock(return_value=_FakeQuestion('s3cret')))
    assert prompts.ask_secret('Pwd:') == 's3cret'


def test_ask_secret_aborted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts.questionary, 'password', MagicMock(return_value=_FakeQuestion(None)))
    with pytest.raises(OdooCLIError):
        prompts.ask_secret('Pwd:')


def test_confirm_returns_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts.questionary, 'confirm', MagicMock(return_value=_FakeQuestion(True)))
    assert prompts.confirm('Sure?') is True


def test_confirm_aborted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts.questionary, 'confirm', MagicMock(return_value=_FakeQuestion(None)))
    with pytest.raises(OdooCLIError):
        prompts.confirm('Sure?')
