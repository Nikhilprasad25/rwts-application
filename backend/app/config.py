"""Global application settings and storage paths.

Working files (uploads, processed datasets, experiment results) default to
``backend/storage``. If the application itself sits inside a cloud-synced folder
— OneDrive, Dropbox, Google Drive — that default is a trap: the sync client
holds transient locks on files the simulator rewrites several times a second,
and it will also try to upload every intermediate result. In that case storage
moves to a local, non-synced directory instead, and anything already written is
migrated across once.

Override explicitly at any time with the ``RWTS_STORAGE`` environment variable.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from app.storage_io import is_cloud_synced

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
FRONTEND_DIR = BASE_DIR.parent / "frontend"

APP_VERSION = "1.0.1"

_DEFAULT_STORAGE = BASE_DIR / "storage"
STORAGE_NOTICE: str | None = None
SYNC_CLIENT: str | None = is_cloud_synced(BASE_DIR)


def _local_fallback() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "RWTS" / "storage"


def _resolve_storage() -> Path:
    global STORAGE_NOTICE
    override = os.environ.get("RWTS_STORAGE")
    if override:
        return Path(override)
    if SYNC_CLIENT:
        target = _local_fallback()
        STORAGE_NOTICE = (
            f"The application folder is inside {SYNC_CLIENT}, which locks files "
            f"while syncing and would interrupt running experiments. Working "
            f"files are stored at {target} instead."
        )
        return target
    return _DEFAULT_STORAGE


STORAGE_DIR = _resolve_storage()
RAW_DIR = STORAGE_DIR / "raw"
PROCESSED_DIR = STORAGE_DIR / "processed"
EXPERIMENT_DIR = STORAGE_DIR / "experiments"
EXPORT_DIR = STORAGE_DIR / "exports"

for _d in (RAW_DIR, PROCESSED_DIR, EXPERIMENT_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _migrate_once() -> None:
    """Copy anything already produced in the in-repo storage folder across."""
    if STORAGE_DIR == _DEFAULT_STORAGE or not _DEFAULT_STORAGE.exists():
        return
    marker = STORAGE_DIR / ".migrated"
    if marker.exists():
        return
    moved = 0
    for sub in ("raw", "processed", "experiments", "exports"):
        src = _DEFAULT_STORAGE / sub
        if not src.exists():
            continue
        for item in src.iterdir():
            if item.name.startswith("."):
                continue
            dest = STORAGE_DIR / sub / item.name
            if dest.exists():
                continue
            try:
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
                moved += 1
            except OSError:                                  # pragma: no cover
                pass
    try:
        marker.write_text(f"migrated {moved} item(s) from {_DEFAULT_STORAGE}")
    except OSError:                                          # pragma: no cover
        pass


_migrate_once()

# ---- upload security limits (section 37 of the specification) ----
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv", ".tsv", ".txt", ".dat"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024        # 200 MB
PREVIEW_ROWS = 100
