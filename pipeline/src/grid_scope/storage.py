from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import duckdb

from grid_scope.connectors.base import CaptureRecord


class RawCaptureStore:
    def __init__(self, raw_dir: Path, database_path: Path) -> None:
        self.raw_dir = raw_dir
        self.database_path = database_path
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_captures (
                    source_id VARCHAR NOT NULL,
                    checksum VARCHAR NOT NULL,
                    path VARCHAR NOT NULL,
                    media_type VARCHAR NOT NULL,
                    retrieved_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (source_id, checksum)
                )
                """
            )

    def save(self, source_id: str, body: bytes, media_type: str) -> CaptureRecord:
        checksum = sha256(body).hexdigest()
        extension = "json" if "json" in media_type else "bin"
        source_dir = self.raw_dir / source_id
        source_dir.mkdir(parents=True, exist_ok=True)
        path = source_dir / f"{checksum}.{extension}"
        if not path.exists():
            path.write_bytes(body)
        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO raw_captures
                VALUES (?, ?, ?, ?, ?)
                """,
                [source_id, checksum, str(path), media_type, datetime.now(UTC)],
            )
        return CaptureRecord(source_id, checksum, path, media_type)

    def latest_path(self, source_id: str) -> Path | None:
        with duckdb.connect(str(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT path FROM raw_captures
                WHERE source_id = ?
                ORDER BY retrieved_at DESC
                LIMIT 1
                """,
                [source_id],
            ).fetchone()
        return Path(row[0]) if row else None
