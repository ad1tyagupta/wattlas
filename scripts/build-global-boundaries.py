#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys
from typing import Any

import httpx
from shapely import make_valid
from shapely.geometry import mapping, shape
from shapely.ops import unary_union


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "src"))

from grid_scope.connectors.geoboundaries import normalize_adm1, validate_india_adm1  # noqa: E402


DEFAULT_METADATA_URL = "https://www.geoboundaries.org/api/current/gbOpen/ALL/ADM1/"


def _iso_lookup(countries: dict[str, Any]) -> dict[str, str]:
    return {
        feature["properties"]["iso3"]: feature["properties"]["id"]
        for feature in countries.get("features", [])
        if feature.get("properties", {}).get("iso3") and feature.get("properties", {}).get("id")
    }


def _download(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "Wattlas/1.0 (public boundary build)"})
        response.raise_for_status()
        return response.json()


def _simplify_geometry(geometry: dict[str, Any], tolerance: float) -> dict[str, Any]:
    value = make_valid(shape(geometry)).simplify(tolerance, preserve_topology=True)
    if value.geom_type not in {"Polygon", "MultiPolygon"}:
        polygons = [part for part in getattr(value, "geoms", []) if part.geom_type in {"Polygon", "MultiPolygon"}]
        value = unary_union(polygons)
    return mapping(value)


def build_boundaries(
    metadata: list[dict[str, Any]],
    countries: dict[str, Any],
    *,
    tolerance: float,
    workers: int,
) -> dict[str, Any]:
    lookup = _iso_lookup(countries)
    records = [item for item in metadata if item.get("boundaryISO") in lookup]
    downloaded: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_download, item["simplifiedGeometryGeoJSON"]): item["boundaryISO"]
            for item in records
        }
        for future in as_completed(futures):
            iso3 = futures[future]
            downloaded[iso3] = future.result()

    features: list[dict[str, Any]] = []
    for iso3 in sorted(downloaded):
        normalized = normalize_adm1(downloaded[iso3], iso2_lookup=lookup)
        for feature in normalized["features"]:
            feature["geometry"] = _simplify_geometry(feature["geometry"], tolerance)
            features.append(feature)

    validate_india_adm1(features)
    return {
        "type": "FeatureCollection",
        "metadata": {
            "source": "geoBoundaries gbOpen ADM1",
            "sourceUrl": "https://www.geoboundaries.org/globalDownloads.html",
            "license": "CC-BY-4.0",
            "release": "9469f09",
            "countries": len({feature["properties"]["country"] for feature in features}),
            "regions": len(features),
            "simplificationTolerance": tolerance,
            "indiaBoundaryPerspective": "Government of India",
            "indiaAttribution": "India boundary perspective: Government of India",
        },
        "features": features,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Wattlas's version-pinned global ADM1 artifact.")
    parser.add_argument("--countries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata-url", default=DEFAULT_METADATA_URL)
    parser.add_argument("--tolerance", type=float, default=0.04)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    countries = json.loads(args.countries.read_text())
    metadata = _download(args.metadata_url)
    result = build_boundaries(metadata, countries, tolerance=args.tolerance, workers=args.workers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    print(f"Wrote {len(result['features'])} ADM1 regions across {result['metadata']['countries']} countries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
