from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from dataclasses import dataclass
import re

import duckdb

from grid_scope.connectors.base import CaptureRecord


@dataclass(frozen=True)
class StoredCapture:
    source_id: str
    checksum: str
    path: Path
    media_type: str
    retrieved_at: datetime


class RawCaptureStore:
    def __init__(self, raw_dir: Path, database_path: Path) -> None:
        self.raw_dir = raw_dir
        self.database_path = database_path
        if self.raw_dir.is_symlink():
            raise ValueError("raw capture directory cannot be a symlink")
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

    @staticmethod
    def _source_id(value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value
        ) is None:
            raise ValueError("raw capture source ID must be a safe bounded slug")
        return value

    @staticmethod
    def _extension(media_type: str) -> str:
        if not isinstance(media_type, str) or not media_type.strip():
            raise ValueError("raw capture media type must be nonblank")
        return "json" if "json" in media_type.lower() else "bin"

    @staticmethod
    def _file_checksum(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _validated_capture(self, row: tuple[object, ...], requested: str) -> StoredCapture | None:
        source_id, checksum, raw_path, media_type, raw_retrieved_at = map(str, row)
        if source_id != requested or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
            return None
        try:
            extension = self._extension(media_type)
        except ValueError:
            return None
        expected_dir = (self.raw_dir / requested).absolute()
        expected_path = (expected_dir / f"{checksum}.{extension}").absolute()
        path = Path(raw_path).absolute()
        if path != expected_path:
            return None
        for candidate in (path, expected_dir, self.raw_dir.absolute()):
            if candidate.is_symlink():
                return None
        if not path.exists() or not path.is_file() or path.is_symlink():
            return None
        try:
            if self._file_checksum(path) != checksum:
                return None
            retrieved_at = datetime.fromisoformat(
                raw_retrieved_at.replace("Z", "+00:00")
            )
        except (OSError, ValueError):
            return None
        if retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=UTC)
        return StoredCapture(
            source_id=source_id, checksum=checksum, path=path,
            media_type=media_type, retrieved_at=retrieved_at,
        )

    def save(self, source_id: str, body: bytes, media_type: str) -> CaptureRecord:
        source_id = self._source_id(source_id)
        extension = self._extension(media_type)
        checksum = sha256(body).hexdigest()
        source_dir = self.raw_dir / source_id
        if source_dir.is_symlink():
            raise ValueError("raw capture source directory cannot be a symlink")
        source_dir.mkdir(parents=True, exist_ok=True)
        path = source_dir / f"{checksum}.{extension}"
        if path.is_symlink():
            raise ValueError("raw capture file cannot be a symlink")
        if path.exists():
            if not path.is_file() or self._file_checksum(path) != checksum:
                raise ValueError("existing raw capture does not match its content address")
        else:
            path.write_bytes(body)
        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute(
                """
                INSERT INTO raw_captures VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (source_id, checksum) DO UPDATE SET
                    path = excluded.path,
                    media_type = excluded.media_type,
                    retrieved_at = excluded.retrieved_at
                """,
                [source_id, checksum, str(path), media_type, datetime.now(UTC)],
            )
        return CaptureRecord(source_id, checksum, path, media_type)

    def latest_path(self, source_id: str) -> Path | None:
        capture = self.latest_capture(source_id)
        return capture.path if capture else None

    def latest_capture(self, source_id: str) -> StoredCapture | None:
        source_id = self._source_id(source_id)
        with duckdb.connect(str(self.database_path)) as connection:
            rows = connection.execute(
                """
                SELECT source_id, checksum, path, media_type,
                       CAST(retrieved_at AS VARCHAR)
                FROM raw_captures
                WHERE source_id = ?
                ORDER BY retrieved_at DESC
                """,
                [source_id],
            ).fetchall()
        for row in rows:
            capture = self._validated_capture(row, source_id)
            if capture is not None:
                return capture
        return None

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
