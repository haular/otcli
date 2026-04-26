# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- Stop persisting derived runtime paths (`client_backup_dir`,
  `clients_config_dir`, `directory_path`, `client_name`) in client TOML
  files. Backups were landing under the legacy `~/.odoo_task_cli_config/`
  tree on installations that had upgraded across the package rename.
- Defensively strip those legacy keys when loading existing TOMLs so the
  bug cannot resurface on user installations that were saved before the
  fix.
- Importing `otcli` no longer creates directories under `$HOME`. The
  data directory layout is now created lazily from the Typer callback,
  which makes the package safe to import in tests, sandboxes, and
  read-only containers.

### Added

- `otcli.paths.Settings` dataclass exposes the resolved filesystem
  layout. Honours the new `OTCLI_HOME` environment variable for use in
  CI and alternative deployments.

### Changed

- Documentation paths updated from `~/.odoo_task_cli_config/` to
  `~/.otcli_config/` to match the runtime behaviour. `GEMINI.md` removed
  (was outdated and not used by Gemini CLI tooling).

## [0.1.0] — initial alpha

- `pg_dump` backup with optional filestore in a single zipped archive,
  including a `manifest.json`.
- Restore via Docker (`psql -v ON_ERROR_STOP=1`) with automatic
  filestore ownership alignment, or via Odoo's HTTP database manager.
- Wraps the official `upgrade.odoo.com` upgrade script.
- Interactive client management with TOML persistence.
- Centralised logging configuration with `--verbose` flag.
- Credential redaction in command echo.
