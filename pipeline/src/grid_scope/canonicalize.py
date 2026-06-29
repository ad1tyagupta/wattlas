from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from math import asin, cos, radians, sin, sqrt
import re
from typing import Any

from shapely.geometry import Point, shape
from shapely.strtree import STRtree


PRECISION_RANK = {"region_centroid": 0, "city_centroid": 1, "exact": 2}
LEVEL_RANK = {"country": 0, "admin_1": 1, "admin_2": 2}
SOURCE_RANK = {
    "official_verified": 4,
    "research_verified": 3,
    "community_mapped": 2,
    "modelled": 1,
}

_NAMESPACE_SPELLINGS = {
    "gemplant": "gemPlant",
    "gemunit": "gemUnit",
    "wikidata": "wikidata",
    "wikipedia": "wikipedia",
}


def canonical_identifier(value: Any) -> str | None:
    """Return a safe lineage identifier without stringifying null sentinels."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None
        return str(int(value)) if float(value).is_integer() else str(value)
    cleaned = str(value).strip()
    if not cleaned or cleaned.casefold() in {
        "none",
        "null",
        "nan",
        "+nan",
        "-nan",
        "inf",
        "+inf",
        "-inf",
        "infinity",
        "+infinity",
        "-infinity",
    }:
        return None
    return cleaned


def canonical_external_namespace(value: Any) -> str | None:
    namespace = canonical_identifier(value)
    if namespace is None:
        return None
    compact = re.sub(r"[^a-z0-9]+", "", namespace.casefold())
    if not compact:
        return None
    return _NAMESPACE_SPELLINGS.get(compact, compact)


def normalize_external_ids(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for raw_namespace, raw_identifier in value.items():
        namespace = canonical_external_namespace(raw_namespace)
        identifier = canonical_identifier(raw_identifier)
        if namespace is not None and identifier is not None:
            normalized[namespace] = identifier
    return dict(sorted(normalized.items()))


def normalize_source_ids(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted(
        {
            identifier
            for raw_identifier in value
            if (identifier := canonical_identifier(raw_identifier)) is not None
        }
    )


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _normalized_text(value: str | None, aliases: dict[str, str]) -> str:
    tokens = re.findall(r"[a-z0-9]+", (value or "").lower())
    expanded: list[str] = []
    for token in tokens:
        expanded.extend(aliases.get(token, token).split())
    return " ".join(expanded)


def _distance_km(first: list[float], second: list[float]) -> float:
    lon1, lat1, lon2, lat2 = map(radians, [first[0], first[1], second[0], second[1]])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    haversine = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(haversine))


def _shared_external_id(first: dict, second: dict) -> bool:
    first_ids = first.get("externalIds") or {}
    second_ids = second.get("externalIds") or {}
    return any(
        value == second_ids.get(namespace)
        for namespace, value in first_ids.items()
        if namespace in second_ids
    )


def _similar_asset(first: dict, second: dict, aliases: dict[str, str]) -> bool:
    if first.get("country") != second.get("country") or first.get("category") != second.get("category"):
        return False
    first_operator = _normalized_text(first.get("operator", ""), aliases)
    second_operator = _normalized_text(second.get("operator", ""), aliases)
    if not first_operator or first_operator != second_operator:
        return False
    first_coordinates = first.get("coordinates")
    second_coordinates = second.get("coordinates")
    if not first_coordinates or not second_coordinates or _distance_km(first_coordinates, second_coordinates) > 50:
        return False
    first_year = first.get("targetYear")
    second_year = second.get("targetYear")
    if first_year and second_year and abs(first_year - second_year) > 1:
        return False
    first_mw = (first.get("demandMw") or {}).get("central")
    second_mw = (second.get("demandMw") or {}).get("central")
    if first_mw and second_mw and not 0.8 <= first_mw / second_mw <= 1.25:
        return False
    first_tokens = set(_normalized_text(first.get("name", ""), aliases).split())
    second_tokens = set(_normalized_text(second.get("name", ""), aliases).split())
    if not first_tokens or not second_tokens:
        return False
    similarity = len(first_tokens & second_tokens) / len(first_tokens | second_tokens)
    return similarity >= 0.6


@dataclass
class _DisjointSet:
    parents: list[int]

    @classmethod
    def create(cls, size: int) -> "_DisjointSet":
        return cls(list(range(size)))

    def find(self, index: int) -> int:
        if self.parents[index] != index:
            self.parents[index] = self.find(self.parents[index])
        return self.parents[index]

    def union(self, first: int, second: int) -> None:
        first_root, second_root = self.find(first), self.find(second)
        if first_root != second_root:
            lower, higher = sorted((first_root, second_root))
            self.parents[higher] = lower


def _normalize_asset_lineage(record: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(record)
    normalized["externalIds"] = normalize_external_ids(normalized.get("externalIds"))
    normalized["sourceIds"] = normalize_source_ids(normalized.get("sourceIds"))
    return normalized


def _record_preference(record: dict[str, Any], field: str) -> tuple[int, int, str]:
    source_rank = SOURCE_RANK.get(record.get("sourceType"), 0)
    precision_rank = (
        PRECISION_RANK.get(record.get("locationPrecision"), -1)
        if field in {"coordinates", "geographyId", "locationPrecision"}
        else -1
    )
    return source_rank, precision_rank, _stable_json(record)


def _combine_external_ids(records: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    values: dict[str, set[str]] = {}
    for record in records:
        for namespace, identifier in record.get("externalIds", {}).items():
            values.setdefault(namespace, set()).add(identifier)
    selected: dict[str, str] = {}
    aliases: dict[str, list[str]] = {}
    for namespace, identifiers in sorted(values.items()):
        candidates = [
            record
            for record in records
            if record.get("externalIds", {}).get(namespace) in identifiers
        ]
        preferred = max(candidates, key=lambda record: _record_preference(record, "externalIds"))
        selected[namespace] = preferred["externalIds"][namespace]
        if len(identifiers) > 1:
            aliases[namespace] = sorted(identifiers)
    return selected, aliases


def _merge_many(records: list[dict[str, Any]]) -> dict[str, Any]:
    excluded = {"aliases", "externalIdAliases", "externalIds", "sourceIds"}
    fields = sorted({field for record in records for field in record} - excluded)
    merged: dict[str, Any] = {}
    for field in fields:
        candidates = [record for record in records if record.get(field) not in (None, "", [], {})]
        if candidates:
            selected = max(candidates, key=lambda record: _record_preference(record, field))
            merged[field] = deepcopy(selected[field])
    merged["sourceIds"] = sorted(
        {source_id for record in records for source_id in record.get("sourceIds", [])}
    )
    external_ids, external_aliases = _combine_external_ids(records)
    merged["externalIds"] = external_ids
    if external_aliases:
        merged["externalIdAliases"] = external_aliases
    merged["aliases"] = sorted(
        {
            value
            for record in records
            for value in [*(record.get("aliases") or []), record.get("name")]
            if value
        }
    )
    return merged


def canonicalize_assets(records: list[dict], *, aliases: dict[str, str] | None = None) -> list[dict]:
    alias_map = {key.lower(): value.lower() for key, value in (aliases or {}).items()}
    normalized = [_normalize_asset_lineage(record) for record in records]
    normalized.sort(key=_stable_json)
    groups = _DisjointSet.create(len(normalized))
    for first_index, first in enumerate(normalized):
        for second_index in range(first_index + 1, len(normalized)):
            second = normalized[second_index]
            if _shared_external_id(first, second) or _similar_asset(first, second, alias_map):
                groups.union(first_index, second_index)
    clusters: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(normalized):
        clusters.setdefault(groups.find(index), []).append(record)
    canonical = [_merge_many(clusters[root]) for root in sorted(clusters)]
    return sorted(canonical, key=lambda record: (str(record.get("id", "")), _stable_json(record)))


def _point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    x, y = point
    inside = False
    if len(ring) < 3:
        return False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside


def _polygon_contains(rings: list[list[list[float]]], point: list[float]) -> bool:
    return bool(
        rings
        and _point_in_ring(point, rings[0])
        and not any(_point_in_ring(point, hole) for hole in rings[1:])
    )


def _contains(geometry: dict, point: list[float]) -> bool:
    if geometry.get("type") == "Polygon":
        return _polygon_contains(geometry.get("coordinates", []), point)
    if geometry.get("type") == "MultiPolygon":
        return any(
            _polygon_contains(polygon, point)
            for polygon in geometry.get("coordinates", [])
        )
    return False


@dataclass(frozen=True)
class GeographyIndex:
    features: tuple[dict, ...]
    geometries: tuple[Any, ...]
    tree: STRtree

    def matching_features(self, coordinates: list[float]) -> list[dict]:
        point = Point(float(coordinates[0]), float(coordinates[1]))
        matches: list[dict] = []
        for index in self.tree.query(point):
            geometry = self.geometries[int(index)]
            if geometry.covers(point):
                matches.append(self.features[int(index)])
        return matches


def build_geography_index(geographies: list[dict]) -> GeographyIndex:
    features: list[dict] = []
    geometries: list[Any] = []
    for feature in geographies:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        candidate = shape(geometry)
        if candidate.is_empty:
            continue
        features.append(feature)
        geometries.append(candidate)
    return GeographyIndex(tuple(features), tuple(geometries), STRtree(geometries))


def _geography_sort_key(feature: dict) -> tuple[int, str, str]:
    properties = feature.get("properties", {})
    level_rank = LEVEL_RANK.get(properties.get("level"), -1)
    identifier = properties.get("id") or feature.get("id") or ""
    return (-level_rank, str(properties.get("parentId") or ""), str(identifier))


def assign_asset_geography(
    asset: dict,
    geographies: list[dict] | GeographyIndex,
) -> str:
    coordinates = asset.get("coordinates")
    if asset.get("locationPrecision") != "exact" or not coordinates:
        return asset["geographyId"]
    if isinstance(geographies, GeographyIndex):
        matches = geographies.matching_features(coordinates)
    else:
        matches = [
            feature
            for feature in geographies
            if _contains(feature.get("geometry") or {}, coordinates)
        ]
    if not matches:
        return asset["geographyId"]
    best = sorted(matches, key=_geography_sort_key)[0]
    return best.get("properties", {}).get("id") or best.get("id") or asset["geographyId"]


def assign_asset_country(asset: dict, countries: list[dict]) -> str | None:
    coordinates = asset.get("coordinates")
    if not coordinates:
        country = asset.get("country")
        return country if country and country != "UNASSIGNED" else None
    for feature in sorted(countries, key=_geography_sort_key):
        if _contains(feature.get("geometry") or {}, coordinates):
            properties = feature.get("properties") or {}
            return properties.get("country") or properties.get("id") or feature.get("id")
    return None
