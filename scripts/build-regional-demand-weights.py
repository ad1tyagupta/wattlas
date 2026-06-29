#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "src"))

from grid_scope.regional_demand import (  # noqa: E402
    build_regional_demand_weights,
    write_regional_demand_weights,
)


def _rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as source:
            return list(csv.DictReader(source))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("records")
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain an array or records object")
    return payload


def _active_ids(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError("boundaries must be a GeoJSON FeatureCollection")
    result: set[str] = set()
    for feature in features:
        properties = feature.get("properties") or {}
        geography_id = str(properties.get("id") or feature.get("id") or "").strip()
        if not geography_id:
            raise ValueError("boundary feature lacks an ADM1 ID")
        if geography_id in result:
            raise ValueError(f"duplicate active ADM1 ID: {geography_id}")
        result.add(geography_id)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build compact normalized Wattlas ADM1 demand weights.")
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--boundaries", type=Path, required=True)
    parser.add_argument("--activity", type=Path)
    parser.add_argument("--industrial", type=Path)
    parser.add_argument("--official-observations", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    population = json.loads(args.population.read_text(encoding="utf-8"))
    artifact = build_regional_demand_weights(
        population_artifact=population,
        active_geography_ids=_active_ids(args.boundaries),
        activity_records=_rows(args.activity),
        industrial_records=_rows(args.industrial),
        official_observations=_rows(args.official_observations),
    )
    write_regional_demand_weights(artifact, args.output)
    print(f"Wrote {len(artifact['records'])} normalized ADM1 demand weights to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
