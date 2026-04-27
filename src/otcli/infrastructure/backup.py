"""Streaming backup of Odoo databases and filestores.

Design goals (rewrite of the legacy "copy-then-zip" pipeline):

* **Constant-disk** during the backup. The legacy flow first dumped the
  database to ``/tmp`` inside the container, ``docker cp``'d the dump
  to a host temp dir, ``shutil.copytree``'d the entire filestore next
  to it, and finally walked the temp dir to produce a zip. For a
  50 GB filestore that meant ~2x the filestore on disk *plus* the zip
  on top. The new pipeline streams everything straight into the zip:

  - ``pg_dump`` is invoked with ``docker exec -i`` and its stdout is
    piped, chunk-by-chunk, into a ``zipfile.open()`` writer.
  - filestore files are walked in place and added with ``zf.write``,
    never copied to a staging area.

  At any time on the host, the only artefact on disk is the partially
  written zip itself.

* **Atomic output**. Writes go to ``<destination>.zip.tmp`` and are
  renamed to the final name only after the zip is closed cleanly.
  Crashes / Ctrl-C / errors leave the previous (or no) zip in place
  rather than a half-written backup.

* **Smart compression**. The SQL dump benefits massively from DEFLATE
  (5-10x typical); filestore attachments are mostly already-compressed
  binaries (PDFs, JPEGs), so we store them with ``ZIP_STORED`` and
  save CPU.

* **Backwards-compatible layout**. The produced zip still exposes
  ``dump.sql`` at the root, ``filestore/<files...>`` and a
  ``manifest.json`` with the same shape as before, so the existing
  restore path keeps working unchanged.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import typer

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import OdooCLIError
from otcli.paths import Settings

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = 'manifest.json'
MANIFEST_VERSION = 1

# 1 MiB chunk for streaming reads from pg_dump stdout into the zip
# entry. Large enough to amortise syscalls, small enough that a
# misbehaving subprocess doesn't balloon RAM.
_STREAM_CHUNK = 1024 * 1024

# Periodic feedback when archiving the filestore (one progress line
# every N files). Tuned for "useful but not spammy".
_FILESTORE_PROGRESS_EVERY = 1000


# --- Public API -----------------------------------------------------------


def backup_odoo(client: ClientConfig, settings: Settings, *, with_filestore: bool) -> Path:
    """Full backup pipeline: DB dump + optional filestore + manifest.

    Streams every byte directly into the final ``.zip`` with no host-side
    temp directory. Returns the absolute path to the produced zip.
    """
    db_name = client.database.db_name
    output_dir = Path(settings.backups_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f'{db_name}_{stamp}'
    final_path = output_dir / f'{backup_name}.zip'
    tmp_path = final_path.with_suffix('.zip.tmp')

    typer.echo(f"Iniciando backup en streaming para '{db_name}'...")

    # If a previous run aborted, stale .tmp may exist; remove it.
    if tmp_path.exists():
        tmp_path.unlink()

    dump_size_bytes = 0
    filestore_file_count = 0
    fs_with_files = False

    try:
        with zipfile.ZipFile(tmp_path, mode='w', allowZip64=True) as zf:
            # 1. Database dump (compressed, streamed via docker exec stdout).
            dump_size_bytes = _stream_database_to_zip(zf, client)

            # 2. Filestore (stored, walked in-place).
            if with_filestore:
                filestore_file_count, fs_with_files = _stream_filestore_to_zip(zf, client)
            else:
                typer.echo('Filestore omitido por solicitud del usuario.')

            # 3. Manifest as the last entry so a partial archive is
            #    obviously incomplete (no manifest -> not a valid otcli
            #    backup).
            _write_manifest_entry(
                zf,
                db_name=db_name,
                with_filestore=with_filestore and fs_with_files,
                dump_size_bytes=dump_size_bytes,
                filestore_file_count=filestore_file_count,
            )
    except BaseException:
        # Anything bad happens -> delete the partial zip and re-raise.
        # ``BaseException`` covers KeyboardInterrupt / SystemExit too.
        tmp_path.unlink(missing_ok=True)
        raise

    # All good; publish atomically.
    os.replace(tmp_path, final_path)

    size_mb = final_path.stat().st_size / (1024 * 1024)
    typer.echo(f'Backup completo: {final_path} ({size_mb:.1f} MB)')
    return final_path


# --- Database dump streaming ---------------------------------------------


def _build_pg_dump_argv(client: ClientConfig) -> list[str]:
    """Build the ``docker exec`` argv that runs pg_dump for ``client``."""
    return [
        'docker',
        'exec',
        '-i',
        client.docker.db_container,
        'pg_dump',
        '-U',
        'odoo',
        '--no-owner',
        '--clean',
        '--if-exists',
        '-d',
        client.database.db_name,
    ]


def _stream_database_to_zip(zf: zipfile.ZipFile, client: ClientConfig) -> int:
    """Run ``pg_dump`` and pipe its stdout straight into ``zf['dump.sql']``.

    Returns the number of bytes written to the dump entry.

    The dump entry is **DEFLATED** because plain SQL compresses extremely
    well. The chunk size is fixed at 1 MiB so memory usage stays
    predictable regardless of the database size.
    """
    typer.echo(f"Volcando base de datos '{client.database.db_name}' (streaming)...")

    argv = _build_pg_dump_argv(client)
    logger.debug('Spawning: %s', ' '.join(argv))

    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    bytes_written = 0
    last_log_threshold = 0
    info = zipfile.ZipInfo('dump.sql', date_time=_now_zip_tuple())
    info.compress_type = zipfile.ZIP_DEFLATED

    try:
        with zf.open(info, mode='w', force_zip64=True) as zentry:
            assert proc.stdout is not None  # for mypy: PIPE is configured
            while True:
                chunk = proc.stdout.read(_STREAM_CHUNK)
                if not chunk:
                    break
                zentry.write(chunk)
                bytes_written += len(chunk)

                # Friendly progress: log every 50 MiB read.
                threshold = bytes_written // (50 * 1024 * 1024)
                if threshold > last_log_threshold:
                    typer.echo(f'  ... volcado en curso: {bytes_written / (1024 * 1024):.0f} MB')
                    last_log_threshold = threshold
    finally:
        # Always reap the subprocess so we never leave zombies.
        proc.stdout.close() if proc.stdout else None
        proc.wait()

    if proc.returncode != 0:
        stderr = proc.stderr.read().decode('utf-8', errors='replace') if proc.stderr else ''
        raise OdooCLIError(f'pg_dump falló (exit={proc.returncode}): {stderr.strip()}')

    if bytes_written == 0:
        raise OdooCLIError(
            f"pg_dump no produjo datos para la base '{client.database.db_name}'. "
            'Verifica que la BD existe y que el contenedor está corriendo.'
        )

    typer.echo(f'  dump.sql escrito ({bytes_written / (1024 * 1024):.1f} MB en disco antes de comprimir)')
    return bytes_written


# --- Filestore streaming -------------------------------------------------


def _stream_filestore_to_zip(zf: zipfile.ZipFile, client: ClientConfig) -> tuple[int, bool]:
    """Walk the host filestore and add every file directly to ``zf``.

    Returns ``(files_added, filestore_had_content)``.

    Files are stored with **ZIP_STORED** because Odoo filestore content
    is overwhelmingly already-compressed binary data (PDFs, images);
    spending CPU on DEFLATE buys almost nothing. If a file vanishes
    between ``walk`` and ``write`` we log and continue: the manifest
    will record the actual count.
    """
    source_filestore_path = os.path.join(client.filestore_dir, client.technical_name)

    if not os.path.isdir(source_filestore_path):
        raise OdooCLIError(
            f'Directorio fuente del filestore no encontrado: {source_filestore_path}. '
            'Revisa filestore_dir y technical_name en la configuración del cliente.'
        )

    typer.echo(f'Archivando filestore desde {source_filestore_path} (sin copia intermedia)...')

    files_added = 0
    files_skipped = 0
    fs_had_content = False

    for dirpath, dirnames, filenames in os.walk(source_filestore_path, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            abs_path = os.path.join(dirpath, name)
            # Build an arcname that lives under "filestore/" inside the
            # zip, mirroring the layout the restore code expects.
            rel_path = os.path.relpath(abs_path, source_filestore_path)
            arcname = os.path.join('filestore', rel_path)

            try:
                # Symlinks: write the *target* contents like the legacy
                # behaviour. Skip dangling links cleanly.
                if os.path.islink(abs_path) and not os.path.exists(abs_path):
                    logger.warning('Skipping dangling symlink: %s', abs_path)
                    files_skipped += 1
                    continue
                zf.write(abs_path, arcname=arcname, compress_type=zipfile.ZIP_STORED)
                files_added += 1
                fs_had_content = True
            except (OSError, zipfile.BadZipFile) as err:
                # The file may have been removed mid-walk by a busy Odoo
                # process; log and keep going.
                logger.warning('Saltando archivo ilegible %s: %s', abs_path, err)
                files_skipped += 1

            if files_added and files_added % _FILESTORE_PROGRESS_EVERY == 0:
                typer.echo(f'  ... {files_added} archivos archivados')

    if not fs_had_content:
        raise OdooCLIError(
            f'El filestore fuente {source_filestore_path} está vacío; no se generará un backup de filestore vacío.'
        )

    if files_skipped:
        typer.echo(f'  ! {files_skipped} archivos saltados (ver log para detalles)')
    typer.echo(f'  filestore archivado: {files_added} archivos')
    return files_added, fs_had_content


# --- Manifest -------------------------------------------------------------


def _write_manifest_entry(
    zf: zipfile.ZipFile,
    *,
    db_name: str,
    with_filestore: bool,
    dump_size_bytes: int,
    filestore_file_count: int,
) -> None:
    """Append the manifest as the very last entry of ``zf``.

    Putting the manifest last is a deliberate signal: a zip that lacks
    the manifest is almost certainly a partial / aborted archive.
    """
    manifest = {
        'manifest_version': MANIFEST_VERSION,
        'created_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'db_name': db_name,
        'has_dump': dump_size_bytes > 0,
        'dump_size_bytes': dump_size_bytes,
        'with_filestore': with_filestore,
        'filestore_file_count': filestore_file_count,
    }
    payload = json.dumps(manifest, indent=2, ensure_ascii=False).encode('utf-8')
    info = zipfile.ZipInfo(MANIFEST_FILENAME, date_time=_now_zip_tuple())
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, payload)


def _now_zip_tuple() -> tuple[int, int, int, int, int, int]:
    """Return ``datetime.now()`` as the 6-tuple zipfile expects."""
    now = datetime.datetime.now()
    return (now.year, now.month, now.day, now.hour, now.minute, now.second)


# --- Legacy / compat helpers ---------------------------------------------
#
# The functions below are still imported by parts of the codebase (most
# notably tests) and are kept as thin wrappers so existing call sites
# keep working. The new streaming pipeline does **not** use them.


def _iter_files(root: str):
    """Yield every regular file under ``root`` (no directories)."""
    if not os.path.isdir(root):
        return
    for dirpath, _, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            yield os.path.join(dirpath, name)


def _copy_filestore(client: ClientConfig, output_path: str) -> str:
    """[Deprecated] Copy the filestore to ``output_path/filestore``.

    Retained for tests and external callers that may still rely on the
    legacy "copy then zip" model. New code should use
    :func:`backup_odoo` which streams directly into the final zip.
    """
    source_filestore_path = os.path.join(client.filestore_dir, client.technical_name)
    if not os.path.isdir(source_filestore_path):
        raise OdooCLIError(
            f'Filestore source directory not found: {source_filestore_path}. '
            f'Check filestore_dir and technical_name in the client config.'
        )

    filestore_dest_path = os.path.join(output_path, 'filestore')
    if os.path.exists(filestore_dest_path):
        shutil.rmtree(filestore_dest_path)
    os.makedirs(filestore_dest_path, exist_ok=True)

    try:
        shutil.copytree(
            source_filestore_path,
            filestore_dest_path,
            symlinks=True,
            ignore_dangling_symlinks=True,
            dirs_exist_ok=True,
        )
    except shutil.Error as err:
        logger.warning('Per-file errors during filestore copy: %s', err)

    src_count = sum(1 for _ in _iter_files(source_filestore_path))
    dst_count = sum(1 for _ in _iter_files(filestore_dest_path))

    if src_count == 0:
        raise OdooCLIError(
            f'Filestore source {source_filestore_path} is empty; refusing to create an empty filestore backup.'
        )

    tolerance = int(os.environ.get('OTCLI_FILESTORE_MISSING_TOLERANCE', '0'))
    missing = src_count - dst_count
    if missing > tolerance:
        raise OdooCLIError(
            f'Filestore verification failed: {missing} of {src_count} files missing '
            f'in the backup destination ({filestore_dest_path}).'
        )

    typer.echo(f'Filestore copied to {filestore_dest_path} ({dst_count}/{src_count} files).')
    return filestore_dest_path


def _build_manifest(
    source_path: str,
    *,
    db_name: str,
    with_filestore: bool,
) -> dict:
    """[Deprecated] Build a manifest by stat'ing files on a staging dir.

    Kept for the few tests that still exercise the file-system flavour
    of the manifest builder.
    """
    filestore_dir = os.path.join(source_path, 'filestore')
    filestore_count = sum(1 for _ in _iter_files(filestore_dir)) if os.path.isdir(filestore_dir) else 0
    dump_path = os.path.join(source_path, 'dump.sql')
    has_dump = os.path.isfile(dump_path) and os.path.getsize(dump_path) > 0

    return {
        'manifest_version': MANIFEST_VERSION,
        'created_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'db_name': db_name,
        'has_dump': has_dump,
        'dump_size_bytes': os.path.getsize(dump_path) if has_dump else 0,
        'with_filestore': with_filestore,
        'filestore_file_count': filestore_count,
    }


def _compress_backup(backup_name: str, source_path: str, output_dir: str) -> str:
    """[Deprecated] Compress ``source_path`` into a zip at ``output_dir``.

    Retained because two test files exercise this path directly. Real
    backups now go through :func:`backup_odoo`.
    """
    zip_path = os.path.join(output_dir, f'{backup_name}.zip')

    filestore_dir = os.path.join(source_path, 'filestore')
    with_filestore = os.path.isdir(filestore_dir) and any(_iter_files(filestore_dir))
    manifest = _build_manifest(
        source_path,
        db_name=backup_name,
        with_filestore=with_filestore,
    )

    manifest_path = os.path.join(source_path, MANIFEST_FILENAME)
    with open(manifest_path, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dirpath, dirnames, filenames in os.walk(source_path):
            dirnames.sort()
            for name in sorted(filenames):
                abs_path = os.path.join(dirpath, name)
                rel_path = os.path.relpath(abs_path, source_path)
                try:
                    zf.write(abs_path, arcname=rel_path)
                except OSError as err:
                    logger.warning('Skipping unreadable file %s: %s', abs_path, err)

    return zip_path
