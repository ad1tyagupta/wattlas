from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse" / "grid_scope.duckdb"
CURATED_PATH = PROJECT_ROOT / "data" / "curated" / "launch-clusters.json"
GLOBAL_ASSETS_PATH = PROJECT_ROOT / "data" / "curated" / "global-assets.json"
GLOBAL_ADMIN1_PATH = PROJECT_ROOT / "data" / "curated" / "global-admin1.geojson"
SOURCE_REGISTRY_PATH = PROJECT_ROOT / "data" / "curated" / "source-registry.json"
PUBLISH_DIR = PROJECT_ROOT / os.getenv("GRID_SCOPE_PUBLISH_DIR", "web/public/data")
UN_GEODATA_URL = os.getenv(
    "UN_GEODATA_URL",
    "https://geoportal.un.org/arcgis/sharing/rest/content/items/"
    "d7caaff3ef4b4f7c82689b7c4694ad92/data",
)
QLEVER_OSM_URL = os.getenv("QLEVER_OSM_URL", "https://qlever.dev/api/osm-planet")
GEM_GIPT_PATH = Path(os.environ["GEM_GIPT_PATH"]) if os.getenv("GEM_GIPT_PATH") else None
GEM_GIPT_URL = os.getenv("GEM_GIPT_URL") or None
WRI_POWER_URL = os.getenv("WRI_POWER_URL") or None
EIA_API_V2_URL = os.getenv("EIA_API_V2_URL") or None
EIA_API_KEY = os.getenv("EIA_API_KEY") or None
REGIONAL_ELECTRICITY_OBSERVED_PATH = Path(
    os.getenv(
        "REGIONAL_ELECTRICITY_OBSERVED_PATH",
        str(PROJECT_ROOT / "data" / "curated" / "regional-electricity-observed.csv"),
    )
)
MODEL_VERSION = "2.1.0"
