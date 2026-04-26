"""Settings derive paths from $HOME (or OTCLI_HOME) without touching disk on construction."""

from __future__ import annotations

from pathlib import Path

from otcli.paths import Settings


def test_settings_default_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('OTCLI_HOME', raising=False)

    s = Settings.from_env()

    assert s.app_data_dir == tmp_path / '.otcli_config'
    assert s.clients_config_dir == tmp_path / '.otcli_config' / 'clientes'
    assert s.backups_dir == tmp_path / '.otcli_config' / 'backups'
    # No I/O on construction.
    assert not s.app_data_dir.exists()


def test_settings_otcli_home_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv('OTCLI_HOME', str(tmp_path / 'custom'))

    s = Settings.from_env()

    assert s.app_data_dir == tmp_path / 'custom'
    assert s.clients_config_dir == tmp_path / 'custom' / 'clientes'
    assert s.backups_dir == tmp_path / 'custom' / 'backups'


def test_ensure_dirs_creates_them(tmp_path: Path) -> None:
    s = Settings(app_data_dir=tmp_path / 'd')

    s.ensure_dirs()

    assert (tmp_path / 'd' / 'clientes').is_dir()
    assert (tmp_path / 'd' / 'backups').is_dir()


def test_ensure_dirs_is_idempotent(tmp_path: Path) -> None:
    s = Settings(app_data_dir=tmp_path / 'd')
    s.ensure_dirs()
    # Second call must not raise.
    s.ensure_dirs()
