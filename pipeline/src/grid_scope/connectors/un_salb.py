from __future__ import annotations

from datetime import UTC, datetime
import json

import httpx

from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState


def normalize_salb(collection: dict) -> dict:
    features: list[dict] = []
    for source in collection.get("features", []):
        properties = source.get("properties") or {}
        identifier = properties.get("salbCode") or properties.get("SALB_CODE")
        country = properties.get("iso2cd") or properties.get("ISO2CD")
        name = properties.get("name") or properties.get("NAME")
        level = properties.get("admLevel") or properties.get("ADM_LEVEL")
        if not identifier or not country or not name or level not in (1, 2):
            raise ValueError("SALB geometry requires an identifier, country, name, and level")
        peer_level = f"admin_{level}"
        features.append(
            {
                "type": "Feature",
                "id": identifier,
                "geometry": source.get("geometry"),
                "properties": {
                    "id": identifier,
                    "name": name,
                    "country": country,
                    "level": peer_level,
                    "parentId": properties.get("parentCode") or properties.get("PARENT_CODE") or country,
                    "peerLevel": peer_level,
                    "sourceId": "un_salb",
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "metadata": {"source": "United Nations Second Administrative Level Boundaries"},
        "features": features,
    }


class UnSalbConnector:
    source_id = "un_salb"

    def __init__(self, urls: list[str]) -> None:
        self.urls = urls

    def fetch(self, client: httpx.Client, *, now: datetime | None = None) -> ConnectorResult:
        checked_at = now or datetime.now(UTC)
        merged = {"type": "FeatureCollection", "features": []}
        for url in self.urls:
            response = client.get(url)
            response.raise_for_status()
            normalized = normalize_salb(response.json())
            merged["features"].extend(normalized["features"])
        merged["metadata"] = {"source": "United Nations SALB"}
        return ConnectorResult(
            source_id=self.source_id,
            state=ConnectorState.CURRENT,
            payload=FetchPayload(
                source_id=self.source_id,
                retrieved_at=checked_at,
                media_type="application/geo+json",
                body=json.dumps(merged, separators=(",", ":")).encode(),
            ),
        )
