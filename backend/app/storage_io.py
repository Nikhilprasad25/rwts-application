"""Filesystem helpers that survive OneDrive, Dropbox and antivirus scanners.

On Windows a synchronising client can hold a transient handle on a file it is
uploading. ``os.replace`` onto that file then fails with ``PermissionError``
(WinError 5 / WinError 32), which is what breaks a naive atomic write. Every
write in this application goes through the retrying helpers below.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

RETRY_ATTEMPTS = 20
RETRY_DELAY = 0.05          # seconds; total worst case ~2 s of backoff


def _replace_with_retry(tmp: Path, target: Path) -> None:
    last: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            os.replace(tmp, target)
            return
        except PermissionError as exc:          # OneDrive / AV holds the target
            last = exc
            time.sleep(RETRY_DELAY * (1 + attempt * 0.5))
        except OSError as exc:                  # pragma: no cover
            last = exc
            time.sleep(RETRY_DELAY)
    # Last resort: write in place. Slightly less atomic, but a stalled sync
    # client must never be able to kill a running experiment.
    try:
        target.write_bytes(tmp.read_bytes())
        tmp.unlink(missing_ok=True)
    except Exception:                            # pragma: no cover
        raise last if last else OSError(f"could not write {target}")


def write_bytes(path: str | Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    _replace_with_retry(tmp, path)


def write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    write_bytes(path, text.encode(encoding))


def write_json(path: str | Path, payload: Any, indent: int = 2) -> None:
    write_text(path, json.dumps(payload, indent=indent, default=str))


def read_json(path: str | Path) -> Any:
    p = Path(path)
    if not p.exists():
        return None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # A concurrent writer was mid-flight; give it a moment.
            time.sleep(RETRY_DELAY)
        except PermissionError:                  # pragma: no cover
            time.sleep(RETRY_DELAY)
    return None


def is_cloud_synced(path: Path) -> str | None:
    """Return the sync client's name when ``path`` lives inside a synced folder."""
    parts = [p.lower() for p in path.parts]
    for marker, label in (("onedrive", "OneDrive"), ("dropbox", "Dropbox"),
                          ("google drive", "Google Drive"),
                          ("googledrive", "Google Drive"),
                          ("icloud drive", "iCloud Drive")):
        if any(marker in p for p in parts):
            return label
    return None
