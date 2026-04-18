"""Functions for backing up Odoo databases and filestores."""

from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import tempfile
import zipfile

import typer

from otcli.bootstrap import config
from otcli.domain.exceptions import OdooCLIError
from otcli.infrastructure.docker import (
    _copy_file_from_container,
    _exec_in_container,
    _get_container,
)

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = 'manifest.json'
MANIFEST_VERSION = 1


def _backup_database(output_path: str) -> str:
    """Dump the configured Odoo database into ``output_path/dump.sql``."""
    db_name = config.db_name
    container_name = config.db_container_name

    backup_file = 'dump.sql'
    temp_path = f'/tmp/{backup_file}'
    final_path = os.path.join(output_path, backup_file)

    typer.echo(f'Backing up database {db_name} from container {container_name}...')

    container = _get_container(container_name)

    typer.echo('Executing pg_dump...')
    # Write inside /tmp so the path is deterministic regardless of the
    # container's working directory.
    _exec_in_container(
        container,
        f'pg_dump -U odoo --no-owner --clean --if-exists -d {db_name} -f {temp_path}',
    )

    typer.echo('Copying backup file from container...')
    _copy_file_from_container(container_name, temp_path, final_path)

    # Best-effort cleanup inside the container.
    _exec_in_container(container, f'rm -f {temp_path}', check=False)

    if not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
        raise OdooCLIError(
            f'Error: The generated backup file {final_path} is empty. Please verify that the selected database is correct.'
        )

    typer.echo(f'Database backup completed: {final_path}')
    return final_path


def _iter_files(root: str):
    """Yield every regular file under ``root`` (no directories)."""
    for dirpath, _, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            yield os.path.join(dirpath, name)


def _copy_filestore(output_path: str) -> str:
    """Copy the configured Odoo client filestore into ``output_path/filestore``.

    Robustness guarantees:
      * the source path is validated up front;
      * symlinks are preserved rather than dereferenced (prevents size
        explosion and follows dangling links safely);
      * per-file errors are logged and do **not** abort the whole copy;
      * a post-copy verification compares file counts between source and
        destination and raises :class:`OdooCLIError` if a significant fraction
        of files is missing (default tolerance: 0 missing).
    """
    source_filestore_path = os.path.join(config.filestore_dir, config.technical_client_name)

    if not os.path.isdir(source_filestore_path):
        raise OdooCLIError(
            f'Filestore source directory not found: {source_filestore_path}. '
            f'Check filestore_dir and technical_client_name in the client config.'
        )

    typer.echo(f'Copying filestore from {source_filestore_path}...')

    filestore_dest_path = os.path.join(output_path, 'filestore')
    # Ensure we start from a clean destination.
    if os.path.exists(filestore_dest_path):
        shutil.rmtree(filestore_dest_path)
    os.makedirs(filestore_dest_path, exist_ok=True)

    errors: list[tuple[str, str, str]] = []

    def _on_copy_error(src_path, dst_path, exc_info):  # pragma: no cover - thin wrapper
        errors.append((str(src_path), str(dst_path), repr(exc_info[1])))

    try:
        shutil.copytree(
            source_filestore_path,
            filestore_dest_path,
            symlinks=True,
            ignore_dangling_symlinks=True,
            dirs_exist_ok=True,
        )
    except shutil.Error as err:
        # ``shutil.copytree`` aggregates per-file errors into a single
        # ``shutil.Error``. Record them but continue.
        for entry in err.args[0] if err.args else []:
            if isinstance(entry, tuple) and len(entry) == 3:
                errors.append((str(entry[0]), str(entry[1]), str(entry[2])))
            else:
                errors.append(('?', '?', repr(entry)))
        logger.warning(
            'Encountered %d per-file errors during filestore copy; continuing.',
            len(errors),
        )

    # Post-copy verification. We count regular files only (symlinks are
    # preserved as-is by copytree with symlinks=True).
    src_count = sum(1 for _ in _iter_files(source_filestore_path))
    dst_count = sum(1 for _ in _iter_files(filestore_dest_path))

    if src_count == 0:
        raise OdooCLIError(
            f'Filestore source {source_filestore_path} is empty; refusing to create an empty filestore backup.'
        )

    # Allow a tiny tolerance for live-write races (default: none).
    tolerance = int(os.environ.get('OTCLI_FILESTORE_MISSING_TOLERANCE', '0'))
    missing = src_count - dst_count
    if missing > tolerance:
        raise OdooCLIError(
            f'Filestore verification failed: {missing} of {src_count} files missing '
            f'in the backup destination ({filestore_dest_path}). Aborting to avoid '
            f'producing an incomplete backup. Set '
            f'OTCLI_FILESTORE_MISSING_TOLERANCE to override.'
        )

    if errors:
        logger.warning('Filestore copy finished with %d per-file warnings (see log).', len(errors))

    typer.echo(f'Filestore copied to {filestore_dest_path} ({dst_count}/{src_count} files).')
    return filestore_dest_path


def _build_manifest(
    source_path: str,
    *,
    db_name: str,
    with_filestore: bool,
) -> dict:
    """Build the manifest that gets embedded in the archive."""
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
    """Create a deflated zip with a ``manifest.json`` describing the contents.

    Returns the absolute path to the produced zip file.
    """
    typer.echo('Compressing backup...')

    zip_path = os.path.join(output_dir, f'{backup_name}.zip')

    # Determine whether filestore is present (dir exists and non-empty).
    filestore_dir = os.path.join(source_path, 'filestore')
    with_filestore = os.path.isdir(filestore_dir) and any(_iter_files(filestore_dir))
    manifest = _build_manifest(
        source_path,
        db_name=backup_name,
        with_filestore=with_filestore,
    )

    # Write the manifest into the staging dir so it's included naturally and
    # its filename is stable for verification.
    manifest_path = os.path.join(source_path, MANIFEST_FILENAME)
    with open(manifest_path, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dirpath, dirnames, filenames in os.walk(source_path):
            # Deterministic order improves reproducibility and manifest parity.
            dirnames.sort()
            for name in sorted(filenames):
                abs_path = os.path.join(dirpath, name)
                rel_path = os.path.relpath(abs_path, source_path)
                try:
                    zf.write(abs_path, arcname=rel_path)
                except OSError as err:
                    logger.warning('Skipping unreadable file %s: %s', abs_path, err)

    typer.echo(f'Backup compressed: {zip_path}')
    return zip_path


def backup_odoo(with_filestore: bool) -> None:
    """Full backup pipeline: DB dump + optional filestore + manifest + zip."""
    db_name = config.db_name
    output_path = config.client_backup_dir
    # Include minute+second to avoid same-day collisions.
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f'{db_name}_{stamp}'

    os.makedirs(output_path, exist_ok=True)

    # Unique staging directory to allow concurrent backups and avoid stale
    # residue from previous failed runs.
    temp_dir = tempfile.mkdtemp(prefix='otcli_backup_', dir=output_path)

    zip_file: str | None = None
    try:
        _backup_database(temp_dir)

        if with_filestore:
            _copy_filestore(temp_dir)
        else:
            os.makedirs(os.path.join(temp_dir, 'filestore'), exist_ok=True)
            typer.echo('Created an empty filestore directory as requested.')

        zip_file = _compress_backup(backup_name, temp_dir, output_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    if not zip_file:  # pragma: no cover - guarded above by try/raise
        raise OdooCLIError('Backup failed: no archive was produced.')

    typer.echo(f'Odoo backup process completed successfully. Backup saved to: {zip_file}')
