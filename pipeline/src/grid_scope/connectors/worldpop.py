from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse

import httpx

from grid_scope.models import ConnectorState


WORLDPOP_SOURCE_ID = "worldpop-global2"
WORLDPOP_LICENCE = "CC-BY-4.0"
WORLDPOP_RELEASE_URL = "https://hub.worldpop.org/Global2"


def checksum_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a release without reading a global raster into memory."""

    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class WorldPopRelease:
    release_id: str
    source_id: str
    source_year: int | None
    path: Path | None
    url: str | None
    checksum_sha256: str | None
    licence: str = WORLDPOP_LICENCE


@dataclass(frozen=True)
class WorldPopResolution:
    state: ConnectorState
    release: WorldPopRelease | None
    message: str | None = None


class WorldPopConnector:
    """Configuration and materialization boundary for public Global2 rasters.

    ``resolve`` never performs network I/O. URL-backed releases must be explicitly
    materialized into the ignored cache by ``download`` before zonal processing.
    """

    def __init__(
        self,
        *,
        path: Path | str | None,
        url: str | None,
        release_id: str,
        source_year: int | None = None,
        expected_checksum_sha256: str | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else None
        self.url = url
        self.release_id = release_id
        self.source_year = source_year
        self.expected_checksum_sha256 = expected_checksum_sha256

    def resolve(self) -> WorldPopResolution:
        if self.path is None and not self.url:
            return WorldPopResolution(
                ConnectorState.NOT_CONFIGURED,
                None,
                "configure a local WorldPop release path or public release URL",
            )
        if self.path is not None:
            if not self.path.is_file():
                return WorldPopResolution(
                    ConnectorState.FAILED,
                    None,
                    f"WorldPop release does not exist: {self.path}",
                )
            checksum = checksum_file(self.path)
            if self.expected_checksum_sha256 and checksum != self.expected_checksum_sha256:
                return WorldPopResolution(
                    ConnectorState.FAILED,
                    None,
                    "WorldPop release checksum does not match configured checksum",
                )
            return WorldPopResolution(
                ConnectorState.CURRENT,
                WorldPopRelease(
                    release_id=self.release_id,
                    source_id=WORLDPOP_SOURCE_ID,
                    source_year=self.source_year,
                    path=self.path,
                    url=self.url,
                    checksum_sha256=checksum,
                ),
            )
        assert self.url is not None
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return WorldPopResolution(ConnectorState.FAILED, None, "invalid WorldPop release URL")
        return WorldPopResolution(
            ConnectorState.CACHED,
            WorldPopRelease(
                release_id=self.release_id,
                source_id=WORLDPOP_SOURCE_ID,
                source_year=self.source_year,
                path=None,
                url=self.url,
                checksum_sha256=self.expected_checksum_sha256,
            ),
            "configured release requires explicit cache materialization",
        )

    def download(self, destination: Path, *, client: httpx.Client) -> WorldPopResolution:
        """Stream a configured public URL to the cache; never bypass access gates."""

        if not self.url:
            return WorldPopResolution(ConnectorState.NOT_CONFIGURED, None, "no public URL configured")
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return WorldPopResolution(ConnectorState.FAILED, None, "invalid WorldPop release URL")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(f"{destination.suffix}.part")
        digest = sha256()
        try:
            with client.stream("GET", self.url, follow_redirects=True) as response:
                response.raise_for_status()
                with temporary.open("wb") as output:
                    for chunk in response.iter_bytes():
                        if chunk:
                            output.write(chunk)
                            digest.update(chunk)
            checksum = digest.hexdigest()
            if self.expected_checksum_sha256 and checksum != self.expected_checksum_sha256:
                temporary.unlink(missing_ok=True)
                return WorldPopResolution(ConnectorState.FAILED, None, "downloaded checksum mismatch")
            temporary.replace(destination)
        except (httpx.HTTPError, OSError) as error:
            temporary.unlink(missing_ok=True)
            return WorldPopResolution(ConnectorState.FAILED, None, str(error))
        return WorldPopConnector(
            path=destination,
            url=self.url,
            release_id=self.release_id,
            source_year=self.source_year,
            expected_checksum_sha256=checksum,
        ).resolve()
