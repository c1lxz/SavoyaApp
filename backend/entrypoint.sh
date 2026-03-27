#!/usr/bin/env sh
set -eu

python -m backend.app.scripts.init_db

python -m backend.app.scripts.cleanup_worker &
CLEANUP_PID=$!

cleanup() {
  kill "$CLEANUP_PID" 2>/dev/null || true
}

trap cleanup INT TERM

exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
