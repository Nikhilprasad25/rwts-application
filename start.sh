#!/usr/bin/env bash
# RWTS research platform - macOS / Linux launcher
set -e
cd "$(dirname "$0")/backend"
PORT="${RWTS_PORT:-8000}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11+ is required but was not found." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment (first run only)..."
  python3 -m venv .venv
  . .venv/bin/activate
  python -m pip install --upgrade pip --quiet
  echo "Installing dependencies - this takes 1-3 minutes the first time..."
  python -m pip install -r requirements.txt
else
  . .venv/bin/activate
fi

( for _ in $(seq 1 120); do
    if (exec 3<>/dev/tcp/127.0.0.1/"$PORT") 2>/dev/null; then
      (command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:$PORT") \
        || (command -v open >/dev/null && open "http://127.0.0.1:$PORT") || true
      break
    fi
    sleep 0.5
  done ) &

echo "Starting server on http://127.0.0.1:$PORT  (Ctrl+C to stop)"
RWTS_PORT="$PORT" python run.py
