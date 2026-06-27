from __future__ import annotations

from datetime import UTC, datetime
import json

import httpx

from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState


UN_BOUNDARY_DISCLAIMER = (
    "The boundaries and names shown and the designations used on this map do not imply "
    "official endorsement or acceptance by the United Nations."
)


def normalize_countries(collection: dict) -> dict:
    features_by_id: dict[str, dict] = {}
    for source in collection.get("features", []):
        if (source.get("geometry") or {}).get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        properties = source.get("properties") or {}
        iso2 = properties.get("iso2cd") or properties.get("ISO2CD")
        if iso2 and (len(iso2) != 2 or not iso2.isalpha() or iso2 != iso2.upper()):
            continue
        if properties.get("stscod") == 99 or properties.get("STSCOD") == 99:
            continue
        if not iso2:
            if properties.get("nam_en") or properties.get("NAME_EN"):
                raise ValueError("UN geometry has no identifiable country")
            continue
        name = properties.get("nam_en") or properties.get("NAME_EN")
        if not name:
            raise ValueError(f"UN country {iso2} has no name")
        geometry = source.get("geometry")
        existing = features_by_id.get(iso2)
        if existing:
            existing_geometry = existing["geometry"]
            existing_polygons = (
                [existing_geometry["coordinates"]]
                if existing_geometry["type"] == "Polygon"
                else existing_geometry["coordinates"]
            )
            new_polygons = (
                [geometry["coordinates"]]
                if geometry["type"] == "Polygon"
                else geometry["coordinates"]
            )
            existing["geometry"] = {
                "type": "MultiPolygon",
                "coordinates": [*existing_polygons, *new_polygons],
            }
            continue
        features_by_id[iso2] = {
            "type": "Feature",
            "id": iso2,
            "geometry": geometry,
            "properties": {
                "id": iso2,
                "name": name,
                "country": iso2,
                "iso3": properties.get("iso3cd") or properties.get("ISO3CD"),
                "m49": properties.get("m49_cd") or properties.get("M49_CD"),
                "level": "country",
                "parentId": None,
                "peerLevel": "country",
                "sourceId": "un_geodata",
            },
        }
    return {
        "type": "FeatureCollection",
        "metadata": {
            "source": "United Nations Geodata simplified",
            "disclaimer": UN_BOUNDARY_DISCLAIMER,
        },
        "features": list(features_by_id.values()),
    }


class UnGeodataConnector:
    source_id = "un_geodata"

    def __init__(self, url: str) -> None:
        self.url = url

    def fetch(self, client: httpx.Client, *, now: datetime | None = None) -> ConnectorResult:
        checked_at = now or datetime.now(UTC)
        response = client.get(self.url)
        response.raise_for_status()
        collection = normalize_countries(response.json())
        if len(collection["features"]) < 190:
            raise ValueError("UN Geodata response contains too few country features")
        return ConnectorResult(
            source_id=self.source_id,
            state=ConnectorState.CURRENT,
            payload=FetchPayload(
                source_id=self.source_id,
                retrieved_at=checked_at,
                media_type="application/geo+json",
                body=json.dumps(collection, separators=(",", ":")).encode(),
            ),
        )
