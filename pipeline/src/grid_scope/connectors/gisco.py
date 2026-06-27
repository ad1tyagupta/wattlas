from __future__ import annotations

from datetime import UTC, datetime
import json

import httpx

from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState


GISCO_NUTS_URL = (
    "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
    "NUTS_RG_20M_2021_4326.geojson"
)


def filter_nuts2(collection: dict) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            feature
            for feature in collection.get("features", [])
            if feature.get("properties", {}).get("LEVL_CODE") == 2
        ],
    }


class GiscoConnector:
    source_id = "gisco"

    def fetch(self, client: httpx.Client, *, now: datetime | None = None) -> ConnectorResult:
        checked_at = now or datetime.now(UTC)
        response = client.get(GISCO_NUTS_URL)
        response.raise_for_status()
        collection = filter_nuts2(response.json())
        if len(collection["features"]) < 250:
            raise ValueError("GISCO response contains too few NUTS 2 features")
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
