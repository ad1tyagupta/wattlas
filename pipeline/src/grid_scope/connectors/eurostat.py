from __future__ import annotations

from datetime import UTC, datetime
import json

import httpx

from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState


EUROSTAT_POPULATION_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
    "demo_r_d2jan?lang=en&time=2024&sex=T&age=TOTAL&unit=NR"
)


def parse_population(payload: dict) -> dict[str, int | None]:
    geo_index = payload["dimension"]["geo"]["category"]["index"]
    values = payload.get("value", {})
    return {
        geo: int(values[str(position)]) if str(position) in values else None
        for geo, position in geo_index.items()
    }


class EurostatConnector:
    source_id = "eurostat"

    def fetch(self, client: httpx.Client, *, now: datetime | None = None) -> ConnectorResult:
        checked_at = now or datetime.now(UTC)
        response = client.get(EUROSTAT_POPULATION_URL)
        response.raise_for_status()
        payload = response.json()
        parse_population(payload)
        return ConnectorResult(
            source_id=self.source_id,
            state=ConnectorState.CURRENT,
            payload=FetchPayload(
                source_id=self.source_id,
                retrieved_at=checked_at,
                media_type="application/json",
                body=json.dumps(payload, separators=(",", ":")).encode(),
            ),
        )
