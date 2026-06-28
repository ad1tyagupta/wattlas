from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Callable

import httpx

from grid_scope.config import (
    CURATED_PATH,
    GLOBAL_ADMIN1_PATH,
    GLOBAL_ASSETS_PATH,
    MODEL_VERSION,
    PUBLISH_DIR,
    QLEVER_OSM_URL,
    RAW_DIR,
    SOURCE_REGISTRY_PATH,
    UN_GEODATA_URL,
    WAREHOUSE_PATH,
)
from grid_scope.canonicalize import assign_asset_country, canonicalize_assets
from grid_scope.connectors.base import ConnectorResult
from grid_scope.connectors.curated import CuratedConnector
from grid_scope.connectors.entsoe import EntsoeConnector
from grid_scope.connectors.eurostat import EurostatConnector, parse_population
from grid_scope.connectors.gisco import GiscoConnector
from grid_scope.connectors.global_assets import load_asset_registry
from grid_scope.connectors.osm_infrastructure import OSM_SOURCE_ID, OsmInfrastructureConnector
from grid_scope.connectors.un_geodata import UnGeodataConnector
from grid_scope.models import ConnectorState
from grid_scope.publisher import SnapshotPublisher
from grid_scope.snapshot_builder import build_global_snapshot_artifacts, build_snapshot_artifacts
from grid_scope.storage import RawCaptureStore


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _network_result(
    fetch: Callable[[], ConnectorResult],
    source_id: str,
    store: RawCaptureStore,
) -> tuple[bytes, ConnectorResult]:
    try:
        result = fetch()
        if result.payload:
            capture = store.save(
                result.source_id,
                result.payload.body,
                result.payload.media_type,
            )
            return capture.path.read_bytes(), result
        raise RuntimeError(result.message or f"{source_id} returned no payload")
    except Exception as error:
        previous = store.latest_path(source_id)
        if previous:
            return previous.read_bytes(), ConnectorResult(
                source_id=source_id,
                state=ConnectorState.FAILED,
                payload=None,
                message=f"Using last successful capture: {error}",
            )
        raise


def merge_asset_feeds(
    countries: dict,
    official_registry: dict,
    osm_payload: dict,
    *,
    observed_at: str,
) -> dict:
    country_features = countries.get("features", [])
    community_assets: list[dict] = []
    for source_asset in osm_payload.get("assets", []):
        asset = dict(source_asset)
        country = assign_asset_country(asset, country_features)
        if not country:
            continue
        asset["country"] = country
        if asset.get("geographyId") == "UNASSIGNED":
            asset["geographyId"] = country
        community_assets.append(asset)

    sources = list(official_registry.get("sources", []))
    if not any(source.get("id") == OSM_SOURCE_ID for source in sources):
        sources.append({
            "id": OSM_SOURCE_ID,
            "name": "OpenStreetMap infrastructure mapping",
            "tier": "C",
            "url": "https://www.openstreetmap.org/copyright",
            "publishedAt": observed_at,
        })
    return {
        **official_registry,
        "sources": sources,
        "assets": canonicalize_assets([
            *community_assets,
            *official_registry.get("assets", []),
        ]),
    }


def refresh() -> Path:
    now = datetime.now(UTC).replace(microsecond=0)
    generated_at = now.isoformat().replace("+00:00", "Z")
    snapshot_id = generated_at.replace(":", "-")
    store = RawCaptureStore(RAW_DIR, WAREHOUSE_PATH)

    with httpx.Client(timeout=90, follow_redirects=True) as client:
        countries_body, countries_status = _network_result(
            lambda: UnGeodataConnector(UN_GEODATA_URL).fetch(client, now=now),
            "un_geodata",
            store,
        )
        gisco_body, gisco_status = _network_result(
            lambda: GiscoConnector().fetch(client, now=now), "gisco", store
        )
        eurostat_body, eurostat_status = _network_result(
            lambda: EurostatConnector().fetch(client, now=now), "eurostat", store
        )
        osm_body, osm_status = _network_result(
            lambda: OsmInfrastructureConnector(QLEVER_OSM_URL).fetch(client, now=now),
            "osm_infrastructure",
            store,
        )

    curated_result = CuratedConnector(CURATED_PATH).fetch(now=now)
    assert curated_result.payload is not None
    store.save(
        curated_result.source_id,
        curated_result.payload.body,
        curated_result.payload.media_type,
    )
    entsoe_status = EntsoeConnector(os.getenv("ENTSOE_SECURITY_TOKEN")).fetch(now=now)

    global_assets_result = CuratedConnector(
        GLOBAL_ASSETS_PATH, source_id="global_assets"
    ).fetch(now=now)
    source_registry_result = CuratedConnector(
        SOURCE_REGISTRY_PATH, source_id="source_registry"
    ).fetch(now=now)
    global_admin1_result = CuratedConnector(
        GLOBAL_ADMIN1_PATH, source_id="geoboundaries_adm1"
    ).fetch(now=now)
    for result in (global_assets_result, source_registry_result, global_admin1_result):
        assert result.payload is not None
        store.save(result.source_id, result.payload.body, result.payload.media_type)

    geometry = json.loads(gisco_body)
    population = parse_population(json.loads(eurostat_body))
    curated = json.loads(curated_result.payload.body)
    europe_artifacts = build_snapshot_artifacts(geometry, population, curated, generated_at)
    registry = load_asset_registry(GLOBAL_ASSETS_PATH, SOURCE_REGISTRY_PATH)
    countries = json.loads(countries_body)
    registry = merge_asset_feeds(
        countries,
        registry,
        json.loads(osm_body),
        observed_at=generated_at,
    )
    registry["modelNote"] = json.loads(GLOBAL_ASSETS_PATH.read_text()).get("modelNote")
    store.save_canonical_assets(registry["assets"])
    artifacts = build_global_snapshot_artifacts(
        countries=countries,
        admin1=json.loads(global_admin1_result.payload.body),
        regions=json.loads(europe_artifacts["regions.geojson"]),
        registry=registry,
        generated_at=generated_at,
    )

    statuses = [
        countries_status,
        gisco_status,
        eurostat_status,
        osm_status,
        global_assets_result,
        source_registry_result,
        global_admin1_result,
        curated_result,
        entsoe_status,
    ]
    country_count = len(json.loads(artifacts["countries.geojson"])["features"])
    asset_features = json.loads(artifacts["assets.geojson"])["features"]
    manifest = {
        "snapshotId": snapshot_id,
        "generatedAt": generated_at,
        "modelVersion": MODEL_VERSION,
        "activeYears": [2026, 2027, 2028, 2029, 2030, 2031],
        "artifacts": {
            "countries": f"snapshots/{snapshot_id}/countries.geojson",
            "admin1": f"snapshots/{snapshot_id}/admin1.geojson",
            "regions": f"snapshots/{snapshot_id}/regions.geojson",
            "assets": f"snapshots/{snapshot_id}/assets.geojson",
            "evidence": f"snapshots/{snapshot_id}/evidence.json",
        },
        "coverage": {
            "countries": country_count,
            "regions": len(json.loads(artifacts["regions.geojson"])["features"]),
            "admin1Regions": len(json.loads(artifacts["admin1.geojson"])["features"]),
            "countriesWithAdmin1": len({
                feature["properties"]["country"]
                for feature in json.loads(artifacts["admin1.geojson"])["features"]
            }),
            "assets": len(asset_features),
            "dataCentres": sum(feature["properties"]["category"] == "data_centre" for feature in asset_features),
            "waterInfrastructure": sum(feature["properties"]["category"] == "water_infrastructure" for feature in asset_features),
        },
        "boundaryDisclaimer": json.loads(artifacts["countries.geojson"]).get("metadata", {}).get("disclaimer"),
        "connectors": [
            {
                "id": result.source_id,
                "state": result.state.value,
                "checkedAt": generated_at,
                "lastSuccessAt": (
                    generated_at
                    if result.state in {ConnectorState.CURRENT, ConnectorState.CACHED}
                    else None
                ),
                "message": result.message,
            }
            for result in statuses
        ],
    }
    return SnapshotPublisher(PUBLISH_DIR).publish(snapshot_id, artifacts, manifest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Wattlas daily snapshot from public sources."
    )
    parser.add_argument("command", nargs="?", choices=["refresh"], default="refresh")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    path = refresh()
    print(f"Published daily snapshot: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
