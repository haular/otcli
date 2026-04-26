# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Removed (BREAKING)

- **Trim configuration surface.** The HTTP-based restore path is gone
  entirely (`infrastructure/odoo_http.py`, `_restore_via_curl`,
  `_prompt_restore_method`). The `[[commands]]` section,
  `database.url`, `database.master_pwd`, and `upgrade.repo_path`
  fields are removed. Pre-1.0 TOMLs that still use them are rejected
  at load time with a clear `ClientConfigError`.
- Drop the `docker` Python SDK runtime dependency. The infrastructure
  layer now talks to Docker via `subprocess` calls to the `docker` CLI
  binary (which is already required to run otcli). This trims about a
  dozen transitive deps (`requests`, `urllib3`, `websocket-client`,
  `paramiko`, `cryptography`, …) at the cost of requiring the `docker`
  binary on `$PATH` (a constraint that already held in practice).
- Drop the `toml` package; reads now use stdlib `tomllib` and writes
  use `tomli-w`. `toml` was unmaintained since 2021.

### Added (post-restore neutralize)

- After a successful restore in a `test` environment, otcli now runs
  `odoo-bin neutralize -d <db>` automatically against the configured
  Odoo install to disable outbound emails, scheduled actions, and
  external integrations. Production environments are never neutralized.
- Failures of the neutralize step are logged at WARNING and reported
  on stderr, but the restore command exits 0 (the database is still in
  place; the user can re-run neutralize manually).

### Added (multi-mode Odoo install support)

- New `[odoo]` section with `install_mode` discriminator. Three modes:
  - `docker`: Odoo runs in a container. Uses `docker exec` and
    auto-detects `odoo-bin` inside the container (`which`,
    `/usr/bin/odoo-bin`, `/mnt/odoo/odoo-bin`, `/opt/odoo/odoo-bin`).
  - `native`: Odoo installed on the host (Debian package or similar).
    Auto-detects via host `which odoo-bin` then `/usr/bin/odoo-bin`.
  - `source`: Odoo cloned from GitHub. Requires explicit
    `odoo.odoo_bin_path` pointing at the script in the clone.
- The wizard branches on `install_mode`: docker asks for the
  container; native and source skip the container question and ask
  for an absolute path with mode-specific guidance.

### Changed

- `[docker]` section trimmed to just `db_container` (PostgreSQL only).
- `odoo_container` moved to `odoo.container_name` (only relevant when
  `install_mode='docker'`).
- `odoo_bin_path` moved to `odoo.odoo_bin_path`.
- Container picker (questionary) is reused for both `db_container` and
  `odoo.container_name`, with graceful fallback to manual entry when
  no Docker containers are running.

### Changed (BREAKING)

- **New TOML schema.** Client configurations now use sectioned TOMLs
  with `[client]`, `[database]`, `[docker]`, `[upgrade]`, and optional
  `[[commands]]` arrays. Pre-1.0 flat configs (e.g. with top-level
  `technical_client_name`, `db_name`, …) are rejected at load time
  with a `ClientConfigError` that points at the README upgrade
  section. There is no automatic migration.
- **Typed configuration model.** The runtime `config` `DotDict` is gone.
  Service entrypoints (`backup_odoo_instance`,
  `restore_odoo_database`, `upgrade_database`) now take an explicit
  `ClientConfig` (and where relevant `Settings`) argument. Callers using
  the public API as a library must build a `ClientConfig` via
  `ClientConfig.from_dict(...)` (or load one with
  `otcli.infrastructure.client_config_io.load`).
- **`otcli.bootstrap` removed.** Resolved into `otcli.paths.Settings` for
  filesystem layout and `otcli.cli.context.AppContext` for per-invocation
  state.
- **`otcli.domain.dotdict` removed.**
- **`otcli.domain.workdir` removed.** Earlier versions called
  `os.chdir(config.directory_path)` from the backup pipeline; the new
  upgrade pipeline manages its own temporary directory and the backup
  pipeline uses absolute paths.
- New `--client` (env var `OTCLI_CLIENT`) global option lets every
  command operate on a specific client without going through the
  interactive selector.

### Added

- `otcli.paths.Settings` dataclass exposes the resolved filesystem
  layout. Honours the new `OTCLI_HOME` environment variable for use in
  CI and alternative deployments.
- Typed `ClientConfig` schema in `otcli.domain.client_config`, with
  validation, defaults (`database.db_name` defaults to
  `client.technical_name`), and explicit error messages.
- `tomli-w` runtime dependency for writing TOML; reads now go through
  stdlib `tomllib`.
- `otcli.infrastructure.client_config_io.{load, save, list_clients}`
  for typed TOML I/O.
- `py.typed` marker (PEP 561) and a public API listed in
  `otcli/__init__.py`.
- GitHub Actions CI workflow (lint, tests, build) and a
  Trusted-Publishing workflow for PyPI release on tag.

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
- Latent `AttributeError` on first upgrade run because `environment`
  was read but never collected during interactive configuration.
  `environment` is now an explicit field of the configuration flow,
  validated against `{'test', 'production'}`.

### Removed

- `linked_production_client` field. It was declared in `DESCRIPTIONS`
  but never asked for and never read; pure dead code.

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
