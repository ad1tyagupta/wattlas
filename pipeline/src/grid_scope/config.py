from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse" / "grid_scope.duckdb"
CURATED_PATH = PROJECT_ROOT / "data" / "curated" / "launch-clusters.json"
GLOBAL_ASSETS_PATH = PROJECT_ROOT / "data" / "curated" / "global-assets.json"
SOURCE_REGISTRY_PATH = PROJECT_ROOT / "data" / "curated" / "source-registry.json"
PUBLISH_DIR = PROJECT_ROOT / os.getenv("GRID_SCOPE_PUBLISH_DIR", "web/public/data")
UN_GEODATA_URL = os.getenv(
    "UN_GEODATA_URL",
    "https://geoportal.un.org/arcgis/sharing/rest/content/items/"
    "d7caaff3ef4b4f7c82689b7c4694ad92/data",
)
QLEVER_OSM_URL = os.getenv("QLEVER_OSM_URL", "https://qlever.dev/api/osm-planet")
MODEL_VERSION = "2.0.0"
