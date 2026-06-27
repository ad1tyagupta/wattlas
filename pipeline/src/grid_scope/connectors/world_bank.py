from __future__ import annotations

from datetime import UTC, datetime
import json

import httpx

from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState


WORLD_BANK_BASE_URL = "https://api.worldbank.org/v2"


def parse_indicator_page(payload: list) -> tuple[dict, list[dict]]:
    if not isinstance(payload, list) or len(payload) != 2:
        raise ValueError("unexpected World Bank indicator response")
    metadata, source_rows = payload
    rows = [
        {
            "countryIso3": row.get("countryiso3code") or None,
            "value": float(row["value"]) if row.get("value") is not None else None,
        }
        for row in (source_rows or [])
        if row.get("countryiso3code")
    ]
    return metadata, rows


class WorldBankConnector:
    source_id = "world_bank"

    def __init__(self, indicator: str, *, base_url: str = WORLD_BANK_BASE_URL) -> None:
        self.indicator = indicator
        self.base_url = base_url.rstrip("/")

    def fetch(self, client: httpx.Client, *, now: datetime | None = None) -> ConnectorResult:
        checked_at = now or datetime.now(UTC)
        page = 1
        rows: list[dict] = []
        total_pages = 1
        while page <= total_pages:
            response = client.get(
                f"{self.base_url}/country/all/indicator/{self.indicator}",
                params={"format": "json", "per_page": 20_000, "page": page},
            )
            response.raise_for_status()
            metadata, page_rows = parse_indicator_page(response.json())
            total_pages = int(metadata.get("pages", 1))
            rows.extend(page_rows)
            page += 1
        body = json.dumps(
            {"indicator": self.indicator, "rows": rows}, separators=(",", ":")
        ).encode()
        return ConnectorResult(
            source_id=self.source_id,
            state=ConnectorState.CURRENT,
            payload=FetchPayload(
                source_id=self.source_id,
                retrieved_at=checked_at,
                media_type="application/json",
                body=body,
            ),
        )
