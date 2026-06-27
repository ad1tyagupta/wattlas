from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_assets (
                    asset_id VARCHAR PRIMARY KEY,
                    payload JSON NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
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

    def save_canonical_assets(self, assets: list[dict]) -> None:
        with duckdb.connect(str(self.database_path)) as connection:
            for asset in assets:
                connection.execute(
                    """
                    INSERT INTO canonical_assets VALUES (?, ?, ?)
                    ON CONFLICT (asset_id) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = excluded.updated_at
                    """,
                    [asset["id"], json.dumps(asset, separators=(",", ":")), datetime.now(UTC)],
                )

    def load_canonical_assets(self) -> list[dict]:
        with duckdb.connect(str(self.database_path)) as connection:
            rows = connection.execute(
                "SELECT payload FROM canonical_assets ORDER BY asset_id"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
