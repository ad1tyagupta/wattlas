from __future__ import annotations

import re
import unicodedata
from typing import Any


SOURCE_ID = "geoboundaries-gbopen-adm1"
INDIA_REQUIRED_REGIONS = (
    "Jammu and Kashmir",
    "Ladakh",
    "Assam",
    "Arunachal Pradesh",
)


def _plain_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_name = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", ascii_name.lower()).strip()


def _india_name(value: str) -> str:
    aliases = {
        "jammu and kashmir": "Jammu and Kashmir",
        "jammu kashmir": "Jammu and Kashmir",
        "ladakh": "Ladakh",
        "assam": "Assam",
        "arunachal pradesh": "Arunachal Pradesh",
    }
    return aliases.get(_plain_name(value), value)


def normalize_adm1(
    collection: dict[str, Any],
    *,
    iso2_lookup: dict[str, str],
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for source_feature in collection.get("features", []):
        source = source_feature.get("properties") or {}
        geometry = source_feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        iso3 = str(source.get("shapeGroup") or "").upper()
        country = iso2_lookup.get(iso3)
        shape_id = str(source.get("shapeID") or "").strip()
        name = str(source.get("shapeName") or "").strip()
        if not country or not shape_id or not name:
            raise ValueError("geoBoundaries ADM1 feature lacks country, shape ID, or name")
        if country == "IN":
            name = _india_name(name)
        feature_id = f"{country}-{shape_id}"
        properties = {
            "id": feature_id,
            "name": name,
            "country": country,
            "level": "admin_1",
            "parentId": country,
            "peerLevel": "admin_1",
            "sourceId": SOURCE_ID,
        }
        if country == "IN":
            properties["boundaryPerspective"] = "government_of_india"
        features.append({
            "type": "Feature",
            "id": feature_id,
            "geometry": geometry,
            "properties": properties,
        })
    return {
        "type": "FeatureCollection",
        "metadata": {
            "source": "geoBoundaries gbOpen ADM1",
            "sourceId": SOURCE_ID,
            "license": "CC-BY-4.0",
        },
        "features": features,
    }


def validate_india_adm1(features: list[dict[str, Any]]) -> None:
    india_names = {
        _plain_name(str((feature.get("properties") or {}).get("name") or ""))
        for feature in features
        if (feature.get("properties") or {}).get("country") == "IN"
    }
    missing = [name for name in INDIA_REQUIRED_REGIONS if _plain_name(name) not in india_names]
    if missing:
        raise ValueError(f"India ADM1 coverage is missing: {', '.join(missing)}")
