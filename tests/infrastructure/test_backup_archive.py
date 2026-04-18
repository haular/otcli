"""Tests for the zip archive builder and manifest contract."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from odoo_task_cli.infrastructure import db_client


def _write(p: Path, content: bytes = b"x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


class TestCompressBackup:
    def test_archive_uses_deflate_compression(self, tmp_path: Path) -> None:
        source = tmp_path / "payload"
        _write(source / "dump.sql", b"SELECT 1;" * 1000)
        _write(source / "filestore" / "aa" / "f.bin", b"p" * 1000)

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        zip_path = db_client._compress_backup("db_2026", str(source), str(out_dir))

        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            assert infos, "zip is empty"
            for info in infos:
                assert info.compress_type == zipfile.ZIP_DEFLATED, (
                    f"{info.filename} not deflated"
                )

    def test_archive_contains_manifest(self, tmp_path: Path) -> None:
        source = tmp_path / "payload"
        _write(source / "dump.sql", b"SELECT 1;")
        _write(source / "filestore" / "aa" / "f1.bin", b"a")
        _write(source / "filestore" / "aa" / "f2.bin", b"b")

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        zip_path = db_client._compress_backup("db_2026", str(source), str(out_dir))

        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            assert "manifest.json" in names
            manifest = json.loads(zf.read("manifest.json"))

        assert manifest["filestore_file_count"] == 2
        assert manifest["has_dump"] is True
        assert "created_at" in manifest
