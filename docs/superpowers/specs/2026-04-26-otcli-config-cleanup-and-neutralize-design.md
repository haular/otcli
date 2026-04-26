# otcli — config cleanup + auto-neutralize design

> Status: approved on 2026-04-26. Proceeding to implementation.

## Goal

Trim the configuration surface before the 1.0.0 release by removing
fields and code paths that are not actually used, add automatic
post-restore neutralization for test databases via `odoo-bin neutralize`,
and align the interactive editor so the Odoo container is picked from a
list of running containers (consistent with how the DB container is
chosen).

## Context (state of repository)

- We are on branch `phase-9-deps-trim`, with phases 1–9 already
  committed. Version is `1.0.0rc1`.
- ClientConfig schema (post-phase-9) has five sections: `[client]`,
  `[database]`, `[docker]`, `[upgrade]`, and `[[commands]]`.
- A grep confirms:
  - `repo_path` is asked, persisted, and **never read**.
  - `commands` (Hash + Shell) has a full submenu but is **never executed**
    by any service.
  - `database.url` and `database.master_pwd` are only used by the HTTP
    restore path (`_restore_via_curl` and `infrastructure/odoo_http.py`).
  - `odoo_container_name` is asked but **never read**; phase-10 connects
    it to the new neutralize flow.

## Decisions taken during brainstorming

| Topic | Decision |
|---|---|
| HTTP restore | Eliminate completely (curl path, `odoo_http.py`, `database.url`, `database.master_pwd`). |
| `repo_path` | Eliminate — dead code. |
| `commands` (Hash/Shell submenu) | Eliminate — dead code. |
| Neutralize trigger | Automatic when `environment == 'test'`, no confirmation. Production never neutralizes. |
| Neutralize fallback | Fail-soft: WARNING + exit 0; the restore itself is considered successful. |
| `odoo-bin` location | Auto-detect first; if it fails, the user is asked for a path during the wizard via a new optional field `docker.odoo_bin_path`. |
| Auto-detect order | `which odoo-bin` → `/usr/bin/odoo-bin` → `/mnt/odoo/odoo-bin` → `/opt/odoo/odoo-bin`. |
| `--addons-path` flag | Don't pass it. If Odoo's neutralize complains, the stderr ends up in the WARNING and the user can address it. |
| `odoo_container_name` UX | Use the same container picker as `db_container_name`. |
| Versioning | Stay on `1.0.0rc1`; tag `1.0.0` once everything is merged. |

## Resulting TOML schema

```toml
[client]
technical_name = "acme"
filestore_dir  = "/var/lib/odoo/filestore"

[database]
db_name = "acme"     # optional; defaults to client.technical_name

[docker]
db_container    = "db"
odoo_container  = "odoo"
odoo_bin_path   = ""              # optional; empty = auto-detect

[upgrade]
target            = "18.0"
code_subscription = "..."
environment       = "test"        # 'test' | 'production'
```

8 visible fields, 4 sections (was 14 / 5).

## Module changes

**Deleted:**

- `src/otcli/infrastructure/odoo_http.py`
- `tests/infrastructure/test_odoo_http.py`
- `_restore_via_curl`, `_prompt_restore_method`, `CommandHash`,
  `CommandShell`, `_parse_command`, the entire `_manage_commands_section`
  family in `services/config_edit.py`.
- Fields: `url`, `master_pwd`, `repo_path`, `commands`.

**Added:**

- `src/otcli/infrastructure/neutralize.py` with
  `neutralize_database(client)` and `_resolve_odoo_bin(client)`.
- `NeutralizeError(OdooCLIError)` in `domain/exceptions.py`.
- `Docker.odoo_bin_path: str = ''` field on the dataclass.

**Modified:**

- `services/restore.py` collapses to the single Docker path and runs
  `neutralize_database(client)` post-restore when
  `client.upgrade.environment == 'test'`. Failures from neutralize are
  logged at WARNING and surfaced to stdout as a `WARNING:` line; the
  restore command exits 0.
- `services/config_edit.py` drops `url`, `master_pwd`, `repo_path` from
  `CONFIG_FIELDS_ORDER` and `DESCRIPTIONS`. Adds `odoo_bin_path` (free
  text, default empty). `odoo_container_name` is wired through
  `_handle_docker_container_selection` like `db_container_name`.
- `cli/app.py` `config show` command updated to print only the surviving
  fields.

## Branching

One branch `phase-10-config-cleanup-and-neutralize`, off `phase-9-deps-trim`.
Three commits inside the branch:

1. `refactor!: drop HTTP restore path and unused config fields`
2. `feat(restore): auto-neutralize test databases via odoo-bin`
3. `feat(cli): use container picker for odoo_container_name`

## Tests

**Removed:** `tests/infrastructure/test_odoo_http.py`.

**Updated:**
- `tests/conftest.py::client_dict` loses `url`, `master_pwd`,
  `repo_path`, `commands`. Gains `docker.odoo_bin_path = ''`.
- `tests/domain/test_client_config.py`: drop tests on `commands` and
  legacy fields; add a test that `Docker.odoo_bin_path` defaults to
  empty and round-trips.
- `tests/infrastructure/test_client_config_io_v2.py`: same fixture
  update.
- Backup/restore/ownership tests: keep as-is, they don't reference the
  removed fields directly.

**Added:**
- `tests/infrastructure/test_neutralize.py`:
  - explicit `odoo_bin_path` is honoured first.
  - auto-detect tries the documented fallbacks in order and returns the
    first that passes `test -x`.
  - all candidates fail → `NeutralizeError` mentioning
    `odoo_bin_path`.
  - successful run produces the expected argv (`odoo-bin neutralize -d
    <db>`).
  - non-zero exit propagates as `NeutralizeError` carrying stderr.
- `tests/services/test_restore_neutralize_integration.py`:
  - `environment='test'` invokes neutralize once after restore.
  - `environment='production'` never invokes neutralize.
  - neutralize failure is logged WARNING and the restore returns
    normally.

## Acceptance

Done when:

- `pytest -q` is green and ≥ 80 tests.
- `ruff check` and `ruff format --check` pass.
- `python -m build` produces `otcli-1.0.0rc1.{tar.gz,whl}` and `twine
  check` passes.
- `otcli --help` shows no traces of removed flows.
- `otcli config show` prints only the surviving fields.
- An integration smoke test (manual): in a fresh `OTCLI_HOME`, register
  a client, observe that the wizard asks 7 fields and uses container
  pickers for both Docker containers.
