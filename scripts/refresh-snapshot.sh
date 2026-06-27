#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHONPATH="$ROOT/pipeline/src" exec "$ROOT/.venv/bin/python" -m grid_scope.cli refresh
