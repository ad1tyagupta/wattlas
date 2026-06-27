from __future__ import annotations

from copy import deepcopy
from math import asin, cos, radians, sin, sqrt
import re


PRECISION_RANK = {"region_centroid": 0, "city_centroid": 1, "exact": 2}
LEVEL_RANK = {"country": 0, "admin_1": 1, "admin_2": 2}


def _normalized_text(value: str, aliases: dict[str, str]) -> str:
    tokens = re.findall(r"[a-z0-9]+", value.lower())
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
    first_ids = set((first.get("externalIds") or {}).values())
    second_ids = set((second.get("externalIds") or {}).values())
    return bool(first_ids & second_ids)


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


def _merge(first: dict, second: dict) -> dict:
    merged = deepcopy(first)
    merged["sourceIds"] = sorted(set(first.get("sourceIds", [])) | set(second.get("sourceIds", [])))
    merged["externalIds"] = {**first.get("externalIds", {}), **second.get("externalIds", {})}
    merged["aliases"] = sorted(
        set(first.get("aliases", []))
        | set(second.get("aliases", []))
        | {first.get("name", ""), second.get("name", "")}
        - {""}
    )
    if PRECISION_RANK.get(second.get("locationPrecision"), -1) > PRECISION_RANK.get(first.get("locationPrecision"), -1):
        merged["locationPrecision"] = second["locationPrecision"]
        merged["coordinates"] = deepcopy(second.get("coordinates"))
        merged["geographyId"] = second.get("geographyId", merged.get("geographyId"))
    return merged


def canonicalize_assets(records: list[dict], *, aliases: dict[str, str] | None = None) -> list[dict]:
    alias_map = {key.lower(): value.lower() for key, value in (aliases or {}).items()}
    canonical: list[dict] = []
    for record in records:
        match_index = next(
            (
                index
                for index, candidate in enumerate(canonical)
                if _shared_external_id(candidate, record)
                or _similar_asset(candidate, record, alias_map)
            ),
            None,
        )
        if match_index is None:
            canonical.append(deepcopy(record))
        else:
            canonical[match_index] = _merge(canonical[match_index], record)
    return canonical


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


def _contains(geometry: dict, point: list[float]) -> bool:
    if geometry.get("type") == "Polygon":
        rings = geometry.get("coordinates", [])
        return bool(rings) and _point_in_ring(point, rings[0])
    if geometry.get("type") == "MultiPolygon":
        return any(polygon and _point_in_ring(point, polygon[0]) for polygon in geometry.get("coordinates", []))
    return False


def assign_asset_geography(asset: dict, geographies: list[dict]) -> str:
    coordinates = asset.get("coordinates")
    if asset.get("locationPrecision") != "exact" or not coordinates:
        return asset["geographyId"]
    matches = [
        feature
        for feature in geographies
        if _contains(feature.get("geometry") or {}, coordinates)
    ]
    if not matches:
        return asset["geographyId"]
    best = max(matches, key=lambda feature: LEVEL_RANK.get(feature.get("properties", {}).get("level"), -1))
    return best.get("properties", {}).get("id") or best.get("id") or asset["geographyId"]
