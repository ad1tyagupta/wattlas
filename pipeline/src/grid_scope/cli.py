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
    MODEL_VERSION,
    PUBLISH_DIR,
    RAW_DIR,
    WAREHOUSE_PATH,
)
from grid_scope.connectors.base import ConnectorResult
from grid_scope.connectors.curated import CuratedConnector
from grid_scope.connectors.entsoe import EntsoeConnector
from grid_scope.connectors.eurostat import EurostatConnector, parse_population
from grid_scope.connectors.gisco import GiscoConnector
from grid_scope.models import ConnectorState
from grid_scope.publisher import SnapshotPublisher
from grid_scope.snapshot_builder import build_snapshot_artifacts
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


def refresh() -> Path:
    now = datetime.now(UTC).replace(microsecond=0)
    generated_at = now.isoformat().replace("+00:00", "Z")
    snapshot_id = generated_at.replace(":", "-")
    store = RawCaptureStore(RAW_DIR, WAREHOUSE_PATH)

    with httpx.Client(timeout=60, follow_redirects=True) as client:
        gisco_body, gisco_status = _network_result(
            lambda: GiscoConnector().fetch(client, now=now), "gisco", store
        )
        eurostat_body, eurostat_status = _network_result(
            lambda: EurostatConnector().fetch(client, now=now), "eurostat", store
        )

    curated_result = CuratedConnector(CURATED_PATH).fetch(now=now)
    assert curated_result.payload is not None
    store.save(
        curated_result.source_id,
        curated_result.payload.body,
        curated_result.payload.media_type,
    )
    entsoe_status = EntsoeConnector(os.getenv("ENTSOE_SECURITY_TOKEN")).fetch(now=now)

    geometry = json.loads(gisco_body)
    population = parse_population(json.loads(eurostat_body))
    curated = json.loads(curated_result.payload.body)
    artifacts = build_snapshot_artifacts(geometry, population, curated, generated_at)

    statuses = [gisco_status, eurostat_status, curated_result, entsoe_status]
    manifest = {
        "snapshotId": snapshot_id,
        "generatedAt": generated_at,
        "modelVersion": MODEL_VERSION,
        "activeYears": [2026, 2027, 2028, 2029, 2030, 2031],
        "artifacts": {
            "regions": f"snapshots/{snapshot_id}/regions.geojson",
            "projects": f"snapshots/{snapshot_id}/projects.geojson",
            "evidence": f"snapshots/{snapshot_id}/evidence.json",
        },
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
        description="Build the GRID//SCOPE daily snapshot from public sources."
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
