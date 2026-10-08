"""Convenience launcher.

    python run.py                 -> http://127.0.0.1:8000
    set RWTS_PORT=8080 & python run.py

If the port is already in use the next free port is tried, so a second copy of
the application never fails with an unhelpful traceback.
"""
from __future__ import annotations

import os
import socket

import uvicorn

HOST = os.environ.get("RWTS_HOST", "127.0.0.1")
START_PORT = int(os.environ.get("RWTS_PORT", "8000"))


def free_port(host: str, start: int, tries: int = 20) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"No free port found between {start} and {start + tries - 1}.")


if __name__ == "__main__":
    port = free_port(HOST, START_PORT)
    if port != START_PORT:
        print(f"Port {START_PORT} was busy — using {port} instead.")
    from app.config import STORAGE_DIR, STORAGE_NOTICE

    if STORAGE_NOTICE:
        print(f"\n  NOTE: {STORAGE_NOTICE}")
    else:
        print(f"\n  Working files: {STORAGE_DIR}")
    print(f"\n  RWTS platform ready at  http://{HOST}:{port}\n")
    uvicorn.run("app.main:app", host=HOST, port=port, reload=False, log_level="info")
