from __future__ import annotations

import json
import math
from collections import defaultdict
from hashlib import sha256
from numbers import Real
from typing import Any, Iterable, Mapping


def _dump(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode()


def _identifier(feature: Mapping[str, Any]) -> str:
    properties = feature.get("properties") or {}
    return str(properties.get("id") or feature.get("id") or "").strip()


def _finite_number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be a finite number")
    return parsed


def _capacity(value: object, *, label: str) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Mapping):
        value = value.get("central")
    parsed = _finite_number(value, label=label)
    if parsed < 0:
        raise ValueError(f"{label} cannot be negative")
    return parsed


def _coordinates(plant: Mapping[str, Any]) -> tuple[float, float]:
    raw = plant.get("coordinates")
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError(f"generator {plant.get('id')} requires point coordinates")
    longitude = _finite_number(raw[0], label="generator longitude")
    latitude = _finite_number(raw[1], label="generator latitude")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError(f"generator {plant.get('id')} has invalid coordinates")
    return longitude, latitude


def _technologies(plant: Mapping[str, Any]) -> list[str]:
    raw = plant.get("technologies")
    if raw is None and plant.get("technology") is not None:
        raw = [plant["technology"]]
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError(f"generator {plant.get('id')} requires a technology")
    technologies = sorted({str(value).strip() for value in raw if str(value).strip()})
    if not technologies:
        raise ValueError(f"generator {plant.get('id')} requires a technology")
    return technologies


def _technology_mix(
    plant: Mapping[str, Any],
    technologies: list[str],
    capacity_mw: float,
) -> dict[str, float]:
    supplied = plant.get("capacityMwByTechnology")
    if supplied is None:
        operating = plant.get("operatingCapacityMwByTechnology") or {}
        planned = plant.get("plannedCapacityMwByTechnology") or {}
        if operating or planned:
            supplied = {
                technology: _capacity(operating.get(technology), label=f"{technology} operating capacity")
                + _capacity(planned.get(technology), label=f"{technology} planned capacity")
                for technology in set(operating) | set(planned)
            }
    if supplied is not None:
        if not isinstance(supplied, Mapping):
            raise ValueError("generator technology capacity mix must be an object")
        mix = {
            str(technology): _capacity(value, label=f"{technology} capacity")
            for technology, value in supplied.items()
        }
        if not math.isclose(sum(mix.values()), capacity_mw, abs_tol=1e-6):
            raise ValueError(f"generator {plant.get('id')} technology capacity does not reconcile")
        return dict(sorted(mix.items()))
    share = capacity_mw / len(technologies)
    return {technology: share for technology in technologies}


def build_generator_artifacts(
    countries: Mapping[str, Any],
    admin1: Mapping[str, Any],
    plants: Iterable[Mapping[str, Any]],
) -> dict[str, bytes]:
    """Build deterministic overview and country-scoped canonical plant shards."""

    country_ids = {_identifier(feature) for feature in countries.get("features", [])}
    country_ids.discard("")
    admin1_country = {
        _identifier(feature): str((feature.get("properties") or {}).get("country") or "").strip()
        for feature in admin1.get("features", [])
        if _identifier(feature)
    }
    by_country: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_ids: set[str] = set()

    for source in plants:
        plant = dict(source)
        plant_id = str(plant.get("id") or "").strip()
        if not plant_id:
            raise ValueError("generator requires a nonblank id")
        if plant_id in seen_ids:
            raise ValueError(f"duplicate generator id: {plant_id}")
        seen_ids.add(plant_id)
        country = str(plant.get("country") or "").strip()
        if country not in country_ids:
            raise ValueError(f"generator {plant_id} has unknown country: {country}")
        geography_id = str(plant.get("geographyId") or "").strip()
        if geography_id not in admin1_country:
            raise ValueError(f"generator {plant_id} has unknown ADM1: {geography_id}")
        if admin1_country[geography_id] != country:
            raise ValueError(f"generator {plant_id} ADM1 does not belong to country {country}")
        source_ids = plant.get("sourceIds")
        if (
            not isinstance(source_ids, list)
            or not source_ids
            or any(not isinstance(value, str) or not value.strip() for value in source_ids)
        ):
            raise ValueError(f"generator {plant_id} requires nonblank public source IDs")
        plant["sourceIds"] = sorted({value.strip() for value in source_ids})
        longitude, latitude = _coordinates(plant)
        technologies = _technologies(plant)
        operating = _capacity(
            plant.get("operatingCapacityMw", plant.get("capacityMw")),
            label=f"generator {plant_id} operating capacity",
        )
        planned = _capacity(
            plant.get("plannedCapacityMw"), label=f"generator {plant_id} planned capacity"
        )
        total = operating + planned
        mix = _technology_mix(plant, technologies, total)
        normalized = {
            **plant,
            "id": plant_id,
            "country": country,
            "geographyId": geography_id,
            "coordinates": [longitude, latitude],
            "technologies": technologies,
            "operatingCapacityMw": operating,
            "plannedCapacityMw": planned,
            "capacityMw": total,
            "technologyMixMw": mix,
        }
        by_country[country].append(normalized)
        by_region[geography_id].append(normalized)

    artifacts: dict[str, bytes] = {}
    index_countries: dict[str, dict[str, Any]] = {}
    total_capacity = 0.0
    for country in sorted(by_country):
        rows = sorted(by_country[country], key=lambda item: item["id"])
        features = []
        for row in rows:
            properties = {key: value for key, value in row.items() if key != "coordinates"}
            features.append({
                "type": "Feature",
                "id": row["id"],
                "geometry": {"type": "Point", "coordinates": row["coordinates"]},
                "properties": properties,
            })
        body = _dump({"type": "FeatureCollection", "features": features})
        path = f"generators/{country}.geojson"
        artifacts[path] = body
        longitudes = [row["coordinates"][0] for row in rows]
        latitudes = [row["coordinates"][1] for row in rows]
        capacity = sum(row["capacityMw"] for row in rows)
        total_capacity += capacity
        index_countries[country] = {
            "bbox": [min(longitudes), min(latitudes), max(longitudes), max(latitudes)],
            "path": path,
            "featureCount": len(rows),
            "checksum": sha256(body).hexdigest(),
            "bytes": len(body),
            "capacityMw": capacity,
        }

    overview_features = []
    for geography_id in sorted(by_region):
        rows = by_region[geography_id]
        operating = sum(row["operatingCapacityMw"] for row in rows)
        planned = sum(row["plannedCapacityMw"] for row in rows)
        mix: dict[str, float] = defaultdict(float)
        for row in rows:
            for technology, capacity in row["technologyMixMw"].items():
                mix[technology] += capacity
        ordered_mix = dict(sorted(mix.items()))
        dominant = min(
            ordered_mix,
            key=lambda technology: (-ordered_mix[technology], technology),
        )
        overview_features.append({
            "type": "Feature",
            "id": geography_id,
            "geometry": {
                "type": "Point",
                "coordinates": [
                    sum(row["coordinates"][0] for row in rows) / len(rows),
                    sum(row["coordinates"][1] for row in rows) / len(rows),
                ],
            },
            "properties": {
                "geographyId": geography_id,
                "country": admin1_country[geography_id],
                "count": len(rows),
                "capacityMw": operating + planned,
                "operatingCapacityMw": operating,
                "plannedCapacityMw": planned,
                "technologyMixMw": ordered_mix,
                "dominantTechnology": dominant,
            },
        })

    artifacts["generator-overview.geojson"] = _dump({
        "type": "FeatureCollection",
        "features": overview_features,
    })
    artifacts["generators/index.json"] = _dump({
        "countries": index_countries,
        "totals": {"featureCount": len(seen_ids), "capacityMw": total_capacity},
    })
    return artifacts
