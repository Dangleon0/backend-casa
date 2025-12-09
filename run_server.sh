#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# Load local environment variables if .env exists
if [ -f ".env" ]; then
  set -a
  source ".env"
  set +a
fi

VENV="${VENV:-.venv}"
PYTHON="${PYTHON:-python3}"

if [ ! -d "$VENV" ]; then
  "$PYTHON" -m venv "$VENV"
fi

source "$VENV/bin/activate"

exec uvicorn app.main:app --reload --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
