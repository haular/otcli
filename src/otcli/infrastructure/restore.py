from __future__ import annotations

import json
import logging
import os
import shutil
import stat
import tempfile
import zipfile

from otcli.domain.client_config import ClientConfig
from otcli.domain.exceptions import OdooCLIError
from otcli.infrastructure.docker import _copy_file_to_container, _exec_in_container, _get_container

logger = logging.getLogger(__name__)


def _validate_backup_zip(backup_file: str) -> None:
    """Fail fast if the zip does not look like an otcli backup.

    We require at least a ``dump.sql`` entry. The manifest is inspected when
    present but is not mandatory (older backups do not have one).
    """
    if not os.path.isfile(backup_file):
        raise OdooCLIError(f'Backup file not found: {backup_file}')

    try:
        with zipfile.ZipFile(backup_file, 'r') as zf:
            names = set(zf.namelist())
            if 'dump.sql' not in names:
                raise OdooCLIError(f"Invalid backup: {backup_file} does not contain a 'dump.sql'.")
            if 'manifest.json' in names:
                try:
                    manifest = json.loads(zf.read('manifest.json'))
                    if not manifest.get('has_dump', True):
                        raise OdooCLIError('Backup manifest reports no database dump present.')
                except json.JSONDecodeError as err:
                    logger.warning('Ignoring unreadable manifest.json: %s', err)
    except zipfile.BadZipFile as err:
        raise OdooCLIError(f'Backup file is not a valid zip: {backup_file}') from err


def _read_reference_ownership(reference: str) -> tuple[int, int, int, int] | None:
    """Return ``(uid, gid, dir_mode, file_mode)`` from ``reference``.

    Returns ``None`` with a WARNING logged if the path is missing or can't be
    ``stat``'d.
    """
    if not os.path.exists(reference):
        logger.warning(
            'Cannot align filestore ownership: reference path %s does not exist.',
            reference,
        )
        return None
    try:
        ref_stat = os.stat(reference)
    except OSError as err:
        logger.warning('Cannot stat reference path %s: %s', reference, err)
        return None

    dir_mode = stat.S_IMODE(ref_stat.st_mode)
    # Drop execute bits from the file mode; filestore attachments are data.
    file_mode = dir_mode & 0o666
    return ref_stat.st_uid, ref_stat.st_gid, dir_mode, file_mode


def _apply_ownership_to_entry(
    entry_path: str,
    *,
    is_dir: bool,
    is_symlink: bool,
    uid: int,
    gid: int,
    dir_mode: int,
    file_mode: int,
) -> str | None:
    """Apply chown/chmod to a single entry.

    Returns ``None`` on success or a short error kind on failure:
    ``'permission'`` (PermissionError) or ``'other'`` (OSError).
    """
    try:
        if is_symlink:
            if os.chown in getattr(os, 'supports_follow_symlinks', set()):
                os.chown(entry_path, uid, gid, follow_symlinks=False)
            else:
                os.chown(entry_path, uid, gid)
            return None

        os.chown(entry_path, uid, gid)
        os.chmod(entry_path, dir_mode if is_dir else file_mode)
        return None
    except PermissionError:
        return 'permission'
    except OSError as err:
        logger.warning('chown/chmod failed on %s: %s', entry_path, err)
        return 'other'


def _iter_paths_for_alignment(root: str):
    """Yield ``(path, is_dir, is_symlink)`` for the root and every descendant."""
    yield root, os.path.isdir(root), os.path.islink(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames:
            full = os.path.join(dirpath, name)
            yield full, True, os.path.islink(full)
        for name in filenames:
            full = os.path.join(dirpath, name)
            yield full, False, os.path.islink(full)


def _align_ownership(path: str, reference: str) -> None:
    """Align owner/group/mode of ``path`` (recursively) with ``reference``.

    This is needed when the CLI runs as a different user than the one that
    owns the host filestore directory (the canonical example is running the
    tool as ``root`` against a filestore owned by UID/GID 1000 belonging to
    the Odoo container user).

    Behaviour:
      * Reads uid/gid and mode from :func:`os.stat` on ``reference``.
      * Applies them recursively to ``path``: directories receive the exact
        reference mode; regular files receive ``reference_mode & 0o666``
        (drop execute bits) so attachments remain readable/writable but not
        executable.
      * On ``PermissionError`` (e.g. not running as root and target belongs
        to someone else), a single actionable WARNING is logged and the
        function returns normally; the restore itself is considered
        successful because the data is in place.
      * If ``reference`` does not exist, a WARNING is logged and the function
        is a no-op.

    Symlinks encountered during traversal are not dereferenced; they are
    chown'd via :func:`os.chown` with ``follow_symlinks=False`` when
    supported. ``os.chmod`` is skipped for symlinks because mode bits on
    symlinks are a no-op on Linux.
    """
    ownership = _read_reference_ownership(reference)
    if ownership is None:
        return
    uid, gid, dir_mode, file_mode = ownership

    permission_denied_reported = False
    for entry_path, is_dir, is_symlink in _iter_paths_for_alignment(path):
        result = _apply_ownership_to_entry(
            entry_path,
            is_dir=is_dir,
            is_symlink=is_symlink,
            uid=uid,
            gid=gid,
            dir_mode=dir_mode,
            file_mode=file_mode,
        )
        if result == 'permission' and not permission_denied_reported:
            logger.warning(
                'No se pudieron ajustar permisos del filestore en %s '
                '(owner esperado %s:%s). '
                'Ejecuta manualmente: sudo chown -R %s:%s %s',
                entry_path,
                uid,
                gid,
                uid,
                gid,
                path,
            )
            permission_denied_reported = True


def _verify_filestore_after_restore(extracted_filestore: str, final_path: str) -> None:
    """Compare file counts between the extracted and final filestore dirs.

    Raises :class:`OdooCLIError` if any files appear to be missing after the
    move, unless ``OTCLI_FILESTORE_MISSING_TOLERANCE`` is set.
    """

    def _count(path: str) -> int:
        total = 0
        for _, _, files in os.walk(path, followlinks=False):
            total += len(files)
        return total

    # ``extracted_filestore`` may have been moved already; compute source count
    # before move if the caller passes the pre-move path.
    src_count = _count(extracted_filestore) if os.path.isdir(extracted_filestore) else 0
    dst_count = _count(final_path)
    tolerance = int(os.environ.get('OTCLI_FILESTORE_MISSING_TOLERANCE', '0'))

    # When called after the move, src_count == 0 and dst_count holds the moved
    # files; we compare against the manifest instead at the caller level.
    if src_count and (src_count - dst_count) > tolerance:
        raise OdooCLIError(
            f'Filestore restore verification failed: {src_count - dst_count} of {src_count} files missing in {final_path}.'
        )


def restore_database_from_container(client: ClientConfig, backup_file: str) -> None:
    """Restore a database dump and its filestore into the configured target.

    Contract:
      * the target database does **not** need to exist up front; it will be
        (re)created;
      * the restore is aborted early if the backup zip is malformed;
      * temporary files are always cleaned up, even on failure;
      * ``psql`` is run with ``ON_ERROR_STOP=1`` so SQL errors surface as
        non-zero exit codes rather than producing a half-restored DB.
    """
    target_db_container_name = client.docker.db_container
    target_db_name = client.database.db_name
    target_filestore_dir = client.filestore_dir

    _validate_backup_zip(backup_file)

    temp_extract_dir = tempfile.mkdtemp(prefix='otcli_restore_')

    try:
        with zipfile.ZipFile(backup_file, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_dir)

        dump_sql_path_host = os.path.join(temp_extract_dir, 'dump.sql')
        filestore_path_host = os.path.join(temp_extract_dir, 'filestore')

        # Load manifest if available for post-restore verification.
        manifest = {}
        manifest_path = os.path.join(temp_extract_dir, 'manifest.json')
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, encoding='utf-8') as fh:
                    manifest = json.load(fh)
            except (OSError, json.JSONDecodeError) as err:
                logger.warning('Unable to parse manifest.json: %s', err)

        logger.info(
            'Restoring database %s in container %s...',
            target_db_name,
            target_db_container_name,
        )
        _copy_file_to_container(target_db_container_name, dump_sql_path_host, '/tmp/dump.sql')

        container = _get_container(target_db_container_name)

        # dropdb is best-effort: the target database may not exist yet. We use
        # --if-exists *and* check=False for maximum robustness across
        # PostgreSQL versions.
        _exec_in_container(
            container,
            f'dropdb -U odoo --if-exists {target_db_name}',
            check=False,
        )
        _exec_in_container(container, f'createdb -U odoo {target_db_name}')
        # ``sh -c`` so ``ON_ERROR_STOP=1`` is interpreted as a psql variable.
        _exec_in_container(
            container,
            (f"sh -c 'psql -U odoo -v ON_ERROR_STOP=1 -d {target_db_name} -f /tmp/dump.sql'"),
        )
        _exec_in_container(container, 'rm -f /tmp/dump.sql', check=False)

        logger.info('Database %s restored successfully.', target_db_name)

        # Restore filestore.
        if os.path.isdir(filestore_path_host) and any(os.scandir(filestore_path_host)):
            final_filestore_path = os.path.join(target_filestore_dir, target_db_name)
            os.makedirs(target_filestore_dir, exist_ok=True)

            logger.info(
                'Moving extracted filestore to final destination: %s',
                final_filestore_path,
            )

            # Count source files *before* moving (shutil.move will remove src).
            src_count = 0
            for _, _, files in os.walk(filestore_path_host, followlinks=False):
                src_count += len(files)

            if os.path.exists(final_filestore_path):
                shutil.rmtree(final_filestore_path)

            shutil.move(filestore_path_host, final_filestore_path)

            dst_count = 0
            for _, _, files in os.walk(final_filestore_path, followlinks=False):
                dst_count += len(files)

            tolerance = int(os.environ.get('OTCLI_FILESTORE_MISSING_TOLERANCE', '0'))
            expected = manifest.get('filestore_file_count', src_count)
            if (expected - dst_count) > tolerance:
                raise OdooCLIError(
                    f'Filestore restore verification failed: expected '
                    f'{expected} files, got {dst_count} in {final_filestore_path}.'
                )

            # Align owner/group/mode with the base filestore directory so that
            # the Odoo container user can read the restored files even when
            # the CLI was run as root (or as a different UID).
            _align_ownership(final_filestore_path, target_filestore_dir)

            logger.info(
                'Filestore restoration completed successfully (%d files).',
                dst_count,
            )
        else:
            logger.info('No filestore found in backup, skipping filestore restoration.')
    finally:
        shutil.rmtree(temp_extract_dir, ignore_errors=True)
