from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from grid_scope.models import AssetProperties, SourceRef


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_asset_registry(assets_path: Path, sources_path: Path) -> dict:
    raw_sources = _load_json(sources_path).get("sources", [])
    sources: list[dict] = []
    source_ids: set[str] = set()
    for raw_source in raw_sources:
        source = SourceRef.model_validate(raw_source)
        scheme = urlparse(str(source.url)).scheme
        if scheme not in {"http", "https"}:
            raise ValueError(f"source {source.id} is not publicly addressable")
        source_ids.add(source.id)
        sources.append(source.model_dump(by_alias=True, mode="json"))

    assets: list[dict] = []
    seen_ids: set[str] = set()
    for raw_asset in _load_json(assets_path).get("assets", []):
        if raw_asset.get("id") in seen_ids:
            raise ValueError(f"duplicate asset id: {raw_asset.get('id')}")
        unknown_sources = set(raw_asset.get("sourceIds", [])) - source_ids
        if unknown_sources:
            raise ValueError(f"asset {raw_asset.get('id')} references unknown source")
        coordinates = raw_asset.get("coordinates")
        if coordinates is not None and (
            len(coordinates) != 2
            or not -180 <= coordinates[0] <= 180
            or not -90 <= coordinates[1] <= 90
        ):
            raise ValueError(f"asset {raw_asset.get('id')} has invalid coordinates")
        asset = AssetProperties.model_validate(raw_asset)
        normalized = dict(raw_asset)
        normalized.update(asset.model_dump(by_alias=True, mode="json"))
        normalized["country"] = raw_asset.get("country") or asset.geography_id.split("-", 1)[0]
        assets.append(normalized)
        seen_ids.add(asset.id)

    return {"sources": sources, "assets": assets}
