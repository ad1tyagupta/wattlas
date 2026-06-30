#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export ADM1_POPULATION_ARTIFACT_PATH="${ADM1_POPULATION_ARTIFACT_PATH:-$ROOT/data/curated/admin1-population.json}"
export REGIONAL_DEMAND_WEIGHTS_PATH="${REGIONAL_DEMAND_WEIGHTS_PATH:-$ROOT/data/curated/regional-demand-weights.json}"
# Compact artifacts above are version checked. The daily job intentionally does
# not invoke the WorldPop raster or model-weight build scripts.
for artifact in "$ADM1_POPULATION_ARTIFACT_PATH" "$REGIONAL_DEMAND_WEIGHTS_PATH"; do
  if [[ ! -s "$artifact" ]]; then
    echo "Required model artifact is missing; refusing to publish: $artifact" >&2
    exit 1
  fi
done
PYTHONPATH="$ROOT/pipeline/src" exec "$ROOT/.venv/bin/python" -m grid_scope.cli refresh
