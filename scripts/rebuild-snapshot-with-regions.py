#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "src"))

from grid_scope.publisher import SnapshotPublisher  # noqa: E402
from grid_scope.snapshot_builder import build_global_snapshot_artifacts  # noqa: E402


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the current Wattlas snapshot with global ADM1 intelligence.")
    parser.add_argument("--public-data", type=Path, default=PROJECT_ROOT / "web" / "public" / "data")
    parser.add_argument("--admin1", type=Path, default=PROJECT_ROOT / "data" / "curated" / "global-admin1.geojson")
    args = parser.parse_args()

    previous = _read(args.public_data / "latest.json")
    countries = _read(args.public_data / previous["artifacts"]["countries"])
    regions = _read(args.public_data / previous["artifacts"]["regions"])
    assets = _read(args.public_data / previous["artifacts"]["assets"])
    evidence = _read(args.public_data / previous["artifacts"]["evidence"])
    admin1 = _read(args.admin1)
    now = datetime.now(UTC).replace(microsecond=0)
    generated_at = now.isoformat().replace("+00:00", "Z")
    snapshot_id = generated_at.replace(":", "-")
    registry = {
        "sources": evidence["sources"],
        "assets": [
            {**feature["properties"], "coordinates": feature["geometry"]["coordinates"]}
            for feature in assets["features"]
        ],
        "modelNote": "Public-source infrastructure context; only forward-looking demand-backed projects affect scores.",
    }
    artifacts = build_global_snapshot_artifacts(
        countries=countries,
        admin1=admin1,
        regions=regions,
        registry=registry,
        generated_at=generated_at,
    )
    asset_features = json.loads(artifacts["assets.geojson"])["features"]
    admin1_features = json.loads(artifacts["admin1.geojson"])["features"]
    connectors = [item for item in previous.get("connectors", []) if item.get("id") != "geoboundaries_adm1"]
    connectors.append({
        "id": "geoboundaries_adm1", "state": "current", "checkedAt": generated_at,
        "lastSuccessAt": generated_at, "message": "Pinned geoBoundaries gbOpen release 9469f09",
    })
    manifest = {
        **previous,
        "snapshotId": snapshot_id,
        "generatedAt": generated_at,
        "modelVersion": "2.1.0",
        "artifacts": {
            "countries": f"snapshots/{snapshot_id}/countries.geojson",
            "admin1": f"snapshots/{snapshot_id}/admin1.geojson",
            "regions": f"snapshots/{snapshot_id}/regions.geojson",
            "assets": f"snapshots/{snapshot_id}/assets.geojson",
            "evidence": f"snapshots/{snapshot_id}/evidence.json",
        },
        "coverage": {
            "countries": len(json.loads(artifacts["countries.geojson"])["features"]),
            "admin1Regions": len(admin1_features),
            "countriesWithAdmin1": len({feature["properties"]["country"] for feature in admin1_features}),
            "regions": len(json.loads(artifacts["regions.geojson"])["features"]),
            "assets": len(asset_features),
            "dataCentres": sum(feature["properties"]["category"] == "data_centre" for feature in asset_features),
            "waterInfrastructure": sum(feature["properties"]["category"] == "water_infrastructure" for feature in asset_features),
        },
        "boundaryDisclaimer": "National geometry follows UN source terms except India, which uses the declared Government of India perspective. Administrative regions use geoBoundaries gbOpen CC BY 4.0.",
        "connectors": connectors,
    }
    destination = SnapshotPublisher(args.public_data).publish(snapshot_id, artifacts, manifest)
    print(f"Published {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
