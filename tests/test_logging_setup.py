"""Tests for the centralised logging configuration."""

from __future__ import annotations

import logging

from otcli import logging_setup


def _root() -> logging.Logger:
    return logging.getLogger()


def test_configure_sets_info_by_default(monkeypatch) -> None:
    # Reset the idempotency guard so the fixture works from any state.
    monkeypatch.setattr(logging_setup, '_CONFIGURED', False)
    for h in list(_root().handlers):
        _root().removeHandler(h)

    logging_setup.configure()
    assert _root().level == logging.INFO
    assert _root().handlers, 'a handler must be installed'


def test_configure_sets_debug_when_verbose(monkeypatch) -> None:
    monkeypatch.setattr(logging_setup, '_CONFIGURED', False)
    for h in list(_root().handlers):
        _root().removeHandler(h)

    logging_setup.configure(verbose=True)
    assert _root().level == logging.DEBUG


def test_configure_is_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(logging_setup, '_CONFIGURED', False)
    for h in list(_root().handlers):
        _root().removeHandler(h)

    logging_setup.configure()
    handler_count = len(_root().handlers)
    logging_setup.configure(verbose=True)
    assert len(_root().handlers) == handler_count, 'must not add a second handler'
    assert _root().level == logging.DEBUG
