# otcli — Odoo Tasks CLI

A small command-line tool that automates **backup**, **restore** and **upgrade**
of Odoo databases running in Docker, including the host-side filestore.

> Status: alpha. Tested against Odoo 16+ with a containerised PostgreSQL.

## Features

- **Backup**: `pg_dump` of the Odoo database plus an optional copy of the
  host filestore, packaged together in a single deflated `.zip` with a
  `manifest.json` describing its contents.
- **Restore (Docker path)**: creates the database if it doesn't exist, drops
  it if it does, streams the dump through `psql` with `ON_ERROR_STOP=1`, and
  moves the filestore back to its canonical location. Owner/group/mode are
  aligned automatically with the base filestore directory so the Odoo
  container can read its own attachments even when the CLI is run as root.
- **Restore (HTTP path)**: posts the archive to
  `POST /web/database/restore` for Odoo instances exposing the database
  manager.
- **Upgrade**: wraps the official `upgrade.odoo.com` upgrade script.
- **Interactive menu** for the same operations, with the client config
  persisted in TOML.

## Installation

Requires Python 3.12+. The canonical workflow uses [`uv`](https://docs.astral.sh/uv/):

```bash
git clone <repository-url>
cd odoo_cli_tool
uv venv
source .venv/bin/activate
uv pip install -e .
```

For the development environment (adds `pytest`, `ruff`, `pre-commit`):

```bash
uv pip install -e ".[dev]"
pre-commit install          # optional, auto-runs ruff on commit
```

## Usage

```bash
otcli --help                # list commands
otcli backup                # backup with filestore (default)
otcli backup --no-filestore # dump only
otcli restore               # interactive restore
otcli upgrade BACKUP.zip    # upgrade a backup file via upgrade.odoo.com
otcli interactive           # menu-driven flow
```

On the first invocation, `otcli` asks you to register a client and writes
`~/.otcli_config/clientes/<client>.toml`. Backups are stored in
`~/.otcli_config/backups/`.

### Environment variables

| Variable | Purpose |
|---|---|
| `OTCLI_HOME` | Override the data directory (default: `~/.otcli_config`). Useful for CI, sandboxes, or alternative deployments. |
| `OTCLI_FILESTORE_MISSING_TOLERANCE` | Accept up to N missing files during filestore backup/restore verification (default: 0, i.e. any loss aborts). |

## Client configuration (TOML)

Each client is a TOML file under `~/.otcli_config/clientes/`. Keys:

| Key | Meaning |
|---|---|
| `environment` | `'test'` or `'production'`. |
| `technical_client_name` | Used as DB name and as the filestore subdirectory. |
| `db_name` | Database name (usually equals `technical_client_name`). |
| `url` | Base URL for HTTP-based restore (e.g. `http://localhost:8069`). |
| `upgrade_target` | Target Odoo version for the upgrade command (e.g. `'18.0'`). |
| `master_pwd` | Odoo master password (HTTP path only). |
| `filestore_dir` | Base path for filestores. `otcli` appends `filestore/<client>` automatically. |
| `code_subscription` | Odoo subscription code for the upgrade service. |
| `db_container_name` | Docker container running PostgreSQL. |
| `odoo_container_name` | Docker container running Odoo. |
| `repo_path` | Absolute path to the project repository (used by the upgrade flow). |

The interactive `otcli` command can create and edit these files for you.

## Upgrading from pre-1.0 installations

Versions prior to 1.0 stored configuration under
`~/.odoo_task_cli_config/`. As of 1.0, the data directory is
`~/.otcli_config/`. **There is no automatic migration.** If you have
pre-1.0 client TOMLs on disk, please reconfigure your clients via
`otcli interactive` (option *Editar Configuración*) — otcli ignores the
legacy directory entirely.

## Project layout

```
src/otcli/
├── __main__.py              # entry point (python -m otcli / otcli)
├── bootstrap.py             # client discovery + global config singleton
├── paths.py                 # Settings dataclass: filesystem layout
├── cli/
│   └── app.py               # Typer application (backup / restore / upgrade / interactive)
├── domain/
│   ├── dotdict.py           # dot-notation dict used for the config object
│   ├── exceptions.py        # OdooCLIError hierarchy
│   ├── shell.py             # subprocess.run wrapper
│   └── workdir.py           # cd into the configured working directory
├── infrastructure/
│   ├── backup.py            # pg_dump + copy filestore + zip (with manifest)
│   ├── client_config.py     # load/save TOML client configs
│   ├── docker.py            # docker SDK helpers
│   ├── odoo_http.py         # HTTP endpoints (restore/drop/list)
│   ├── restore.py           # Docker-path restore + ownership alignment
│   └── upgrade.py           # wrapper around upgrade.odoo.com
└── services/
    ├── _prompts.py          # interactive prompt helpers
    ├── backup.py            # backup orchestration
    ├── config_edit.py       # interactive TOML editor
    ├── restore.py           # restore orchestration (Docker or HTTP)
    └── upgrade.py           # upgrade orchestration
```

## Development

```bash
# Run the test suite
python -m pytest tests/

# Lint and format
ruff check src/ tests/
ruff format src/ tests/
```

## License

MIT — see `LICENSE`.
