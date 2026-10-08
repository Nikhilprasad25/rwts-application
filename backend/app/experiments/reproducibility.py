"""Reproducibility helpers: config fingerprinting and environment capture."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from typing import Any

import numpy
import pandas
import scipy

from app.config import APP_VERSION


def fingerprint(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def environment() -> dict[str, Any]:
    return {
        "app_version": APP_VERSION,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "scipy": scipy.__version__,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
