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
    first_signature = _asset_name_signature(first, aliases)
    second_signature = _asset_name_signature(second, aliases)
    if not first_signature or first_signature != second_signature:
        return False
    return True


def _asset_name_signature(record: dict[str, Any], aliases: dict[str, str]) -> tuple[str, ...]:
    return tuple(sorted(_normalized_text(record.get("name", ""), aliases).split()))


def _asset_capacity_band(record: dict[str, Any]) -> int | None:
    central = (record.get("demandMw") or {}).get("central")
    if central is None:
        return None
    capacity = float(central)
    if not math.isfinite(capacity) or capacity < 0:
        return None
    if capacity == 0:
        return 0
    return int(math.floor(math.log(capacity) / math.log(1.25)))


def _asset_spatial_cell(record: dict[str, Any]) -> tuple[int, int] | None:
    coordinates = record.get("coordinates")
    if not coordinates:
        return None
    return math.floor(float(coordinates[0])), math.floor(float(coordinates[1]))


def _asset_fuzzy_key(
    record: dict[str, Any], aliases: dict[str, str]
) -> tuple[str, str, str, tuple[str, ...], tuple[int, int], int, int] | None:
    country = str(record.get("country") or "")
    category = str(record.get("category") or "")
    operator = _normalized_text(record.get("operator", ""), aliases)
    signature = _asset_name_signature(record, aliases)
    cell = _asset_spatial_cell(record)
    target_year = record.get("targetYear")
    capacity_band = _asset_capacity_band(record)
    if (
        not country
        or not category
        or not operator
        or not signature
        or cell is None
        or not isinstance(target_year, int)
        or capacity_band is None
    ):
        return None
    return country, category, operator, signature, cell, target_year, capacity_band


def _asset_candidate_keys(
    record: dict[str, Any], aliases: dict[str, str]
) -> list[tuple[Any, ...]]:
    base = _asset_fuzzy_key(record, aliases)
    if base is None:
        return []
    country, category, operator, signature, cell, target_year, capacity_band = base
    return [
        (
            country,
            category,
            operator,
            signature,
            cell[0] + longitude_offset,
            cell[1] + latitude_offset,
            target_year + year_offset,
            capacity_band + capacity_offset,
        )
        for longitude_offset in (-1, 0, 1)
        for latitude_offset in (-1, 0, 1)
        for year_offset in (-1, 0, 1)
        for capacity_offset in (-1, 0, 1)
    ]


def _asset_insertion_key(
    record: dict[str, Any], aliases: dict[str, str]
) -> tuple[Any, ...] | None:
    base = _asset_fuzzy_key(record, aliases)
    if base is None:
        return None
    country, category, operator, signature, cell, target_year, capacity_band = base
    return (
        country,
        category,
        operator,
        signature,
        cell[0],
        cell[1],
        target_year,
        capacity_band,
    )


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
    exact_index: dict[tuple[str, str], set[int]] = {}
    fuzzy_index: dict[tuple[Any, ...], dict[int, int]] = {}

    for index, record in enumerate(normalized):
        exact_candidates: set[int] = set()
        for token in record.get("externalIds", {}).items():
            roots = {groups.find(candidate) for candidate in exact_index.get(token, set())}
            exact_index[token] = roots
            exact_candidates.update(roots)
        for candidate in sorted(exact_candidates):
            groups.union(index, candidate)

        fuzzy_candidates: dict[int, int] = {}
        candidate_keys = _asset_candidate_keys(record, alias_map)
        for key in candidate_keys:
            representatives = {
                groups.find(candidate): candidate
                for candidate in fuzzy_index.get(key, {}).values()
            }
            fuzzy_index[key] = representatives
            fuzzy_candidates.update(representatives)
        for candidate in sorted(fuzzy_candidates.values()):
            if groups.find(index) != groups.find(candidate) and _similar_asset(
                record, normalized[candidate], alias_map
            ):
                groups.union(index, candidate)

        for token in record.get("externalIds", {}).items():
            roots = {groups.find(candidate) for candidate in exact_index.get(token, set())}
            roots.add(groups.find(index))
            exact_index[token] = roots
        insertion_key = _asset_insertion_key(record, alias_map)
        if insertion_key is not None:
            representatives = {
                groups.find(candidate): candidate
                for candidate in fuzzy_index.get(insertion_key, {}).values()
            }
            representatives.setdefault(groups.find(index), index)
            fuzzy_index[insertion_key] = representatives
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
    matches = matching_asset_geographies(asset, geographies)
    if not matches:
        return asset["geographyId"]
    best = matches[0]
    return best.get("properties", {}).get("id") or best.get("id") or asset["geographyId"]


def matching_asset_geographies(
    asset: dict,
    geographies: list[dict] | GeographyIndex,
) -> list[dict]:
    coordinates = asset.get("coordinates")
    if asset.get("locationPrecision") != "exact" or not coordinates:
        return []
    if isinstance(geographies, GeographyIndex):
        matches = geographies.matching_features(coordinates)
    else:
        matches = [
            feature
            for feature in geographies
            if _contains(feature.get("geometry") or {}, coordinates)
        ]
    return sorted(matches, key=_geography_sort_key)


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
