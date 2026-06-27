from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse" / "grid_scope.duckdb"
CURATED_PATH = PROJECT_ROOT / "data" / "curated" / "launch-clusters.json"
PUBLISH_DIR = PROJECT_ROOT / os.getenv("GRID_SCOPE_PUBLISH_DIR", "web/public/data")
MODEL_VERSION = "1.0.0"
