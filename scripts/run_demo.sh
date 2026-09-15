#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
DEMO_OUTPUT="${DEMO_OUTPUT:-output/demo}"
"$PYTHON_BIN" -m mightyeye_observations.cli demo --output "$DEMO_OUTPUT"
export DATABASE_URL="sqlite:///$PWD/$DEMO_OUTPUT/mightyeye.db"
export EVIDENCE_ROOT="$PWD/$DEMO_OUTPUT/evidence"
export MIGHTYEYE_MODE=synthetic
exec "$PYTHON_BIN" -m mightyeye_observations.cli serve --host 127.0.0.1 --port "${PORT:-8000}"
