#!/usr/bin/env bash
# one-shot demo launcher: API on :8000 (serves web/dist if built)
set -e
cd "$(dirname "$0")/.."
python3 -m pytest -q engine/tests api
exec python3 -m uvicorn api.main:app --port 8000
