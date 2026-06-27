from __future__ import annotations

from datetime import datetime

from grid_scope.connectors.base import ConnectorResult
from grid_scope.models import ConnectorState


class EntsoeConnector:
    source_id = "entsoe"

    def __init__(self, token: str | None) -> None:
        self.token = token.strip() if token else None

    def fetch(self, *, now: datetime) -> ConnectorResult:
        if not self.token:
            return ConnectorResult(
                source_id=self.source_id,
                state=ConnectorState.NOT_CONFIGURED,
                payload=None,
                message="ENTSO-E security token is not configured.",
            )
        return ConnectorResult(
            source_id=self.source_id,
            state=ConnectorState.CACHED,
            payload=None,
            message="Token configured; zone queries run during scheduled refresh.",
        )
