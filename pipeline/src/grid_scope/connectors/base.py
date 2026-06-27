from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from grid_scope.models import ConnectorState


@dataclass(frozen=True)
class FetchPayload:
    source_id: str
    retrieved_at: datetime
    media_type: str
    body: bytes


@dataclass(frozen=True)
class ConnectorResult:
    source_id: str
    state: ConnectorState
    payload: FetchPayload | None
    message: str | None = None


@dataclass(frozen=True)
class CaptureRecord:
    source_id: str
    checksum: str
    path: Path
    media_type: str
