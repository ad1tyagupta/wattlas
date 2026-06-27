from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState


class CuratedConnector:
    source_id = "curated_evidence"

    def __init__(self, path: Path) -> None:
        self.path = path

    def fetch(self, *, now: datetime | None = None) -> ConnectorResult:
        body = self.path.read_bytes()
        return ConnectorResult(
            source_id=self.source_id,
            state=ConnectorState.CURRENT,
            payload=FetchPayload(
                source_id=self.source_id,
                retrieved_at=now or datetime.now(UTC),
                media_type="application/json",
                body=body,
            ),
        )
