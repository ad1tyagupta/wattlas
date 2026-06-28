from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
import re
from typing import Any, Iterable

from grid_scope.canonicalize import _distance_km, assign_asset_geography


SOURCE_RANK = {
    "official_verified": 4,
    "research_verified": 3,
    "community_mapped": 2,
    "modelled": 1,
}

_VALUE_KIND_RANK = {
    "unavailable": 0,
    "inherited": 1,
    "estimated": 2,
    "observed": 3,
    "reported": 3,
}
_TECHNOLOGIES = {
    "solar",
    "wind",
    "hydro",
    "nuclear",
    "gas",
    "coal",
    "oil",
    "biomass",
    "geothermal",
    "other",
}
_GENERIC_PLANT_WORDS = {
    "electric",
    "electricity",
    "generating",
    "generation",
    "plant",
    "power",
    "project",
    "station",
}
_UNIT_ID_NAMESPACES = {"gemunit", "unit", "unitid", "officialunit"}
_OPERATING_LIFECYCLES = {"operational"}
_PLANNED_LIFECYCLES = {"announced", "planning_filed", "permitted", "under_construction"}

_FIELD_KIND_NAMES = {
    "capacityMw": "capacityValueKind",
    "dependableCapacityMw": "dependableCapacityValueKind",
    "annualGenerationGwh": "generationValueKind",
}


@dataclass
class _DisjointSet:
    parents: list[int]

    @classmethod
    def create(cls, size: int) -> "_DisjointSet":
        return cls(list(range(size)))

    def find(self, index: int) -> int:
        parent = self.parents[index]
        if parent != index:
            self.parents[index] = self.find(parent)
        return self.parents[index]

    def union(self, first: int, second: int) -> None:
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root != second_root:
            lower, higher = sorted((first_root, second_root))
            self.parents[higher] = lower


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _normalized_text(value: Any, aliases: dict[str, str]) -> str:
    tokens = _key(value).split()
    expanded: list[str] = []
    for token in tokens:
        expanded.extend(aliases.get(token, token).split())
    return " ".join(expanded)


def _name_tokens(value: Any, aliases: dict[str, str]) -> set[str]:
    return {
        token
        for token in _normalized_text(value, aliases).split()
        if token not in _GENERIC_PLANT_WORDS
    }


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _normalize_lifecycle(record: dict[str, Any]) -> tuple[str, str | None]:
    source_lifecycle = _key(record.get("lifecycle"))
    raw_status = _clean_text(record.get("rawStatus"))
    aliases = {
        "operating": "operational",
        "operational": "operational",
        "construction": "under_construction",
        "under construction": "under_construction",
        "under_construction": "under_construction",
        "planned": "announced",
        "proposed": "announced",
        "pre construction": "announced",
        "announced": "announced",
        "planning filed": "planning_filed",
        "planning_filed": "planning_filed",
        "permitted": "permitted",
        "mothballed": "paused",
        "mothball": "paused",
        "paused": "paused",
        "shelved": "paused",
        "inactive": "paused",
        "retired": "cancelled",
        "decommissioned": "cancelled",
        "cancelled": "cancelled",
        "canceled": "cancelled",
    }
    canonical = aliases.get(source_lifecycle)
    if canonical is None:
        raise ValueError(f"unsupported power-plant lifecycle: {record.get('lifecycle')}")
    if source_lifecycle in {"shelved", "retired", "decommissioned", "mothballed", "mothball"}:
        raw_status = source_lifecycle
    return canonical, raw_status


def _normalize_range(value: Any, *, field: str) -> dict[str, float] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number or range")
    if isinstance(value, (int, float)):
        number = float(value)
        values = {"low": number, "central": number, "high": number}
    elif isinstance(value, dict):
        try:
            values = {part: float(value[part]) for part in ("low", "central", "high")}
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{field} must contain numeric low, central, and high values") from error
    else:
        raise ValueError(f"{field} must be a number or range")
    if any(not math.isfinite(number) for number in values.values()):
        raise ValueError(f"{field} must contain only finite numbers")
    if any(number < 0 for number in values.values()):
        raise ValueError(f"{field} cannot be negative")
    if not values["low"] <= values["central"] <= values["high"]:
        raise ValueError(f"{field} must satisfy low <= central <= high")
    return values


def _normalize_external_ids(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized = {
        str(namespace).strip(): str(external_id).strip()
        for namespace, external_id in value.items()
        if str(namespace).strip() and str(external_id).strip()
    }
    return dict(sorted(normalized.items()))


def _normalize_record(record: dict[str, Any], geographies: list[dict] | None) -> dict[str, Any]:
    normalized = deepcopy(record)
    normalized["category"] = "power_generation"
    technology = _key(normalized.get("technology")).replace(" ", "_") or "other"
    normalized["technology"] = technology if technology in _TECHNOLOGIES else "other"
    normalized["capacityMw"] = _normalize_range(normalized.get("capacityMw"), field="capacityMw")
    normalized["dependableCapacityMw"] = _normalize_range(
        normalized.get("dependableCapacityMw"), field="dependableCapacityMw"
    )
    annual_generation = normalized.get("annualGenerationGwh")
    if annual_generation is None and normalized.get("reportedGenerationGwh") is not None:
        annual_generation = normalized.get("reportedGenerationGwh")
        normalized.setdefault("generationValueKind", "reported")
    normalized["annualGenerationGwh"] = _normalize_range(
        annual_generation, field="annualGenerationGwh"
    )
    normalized.pop("reportedGenerationGwh", None)

    lifecycle, raw_status = _normalize_lifecycle(normalized)
    normalized["lifecycle"] = lifecycle
    if raw_status is not None:
        normalized["rawStatus"] = raw_status

    normalized["externalIds"] = _normalize_external_ids(normalized.get("externalIds"))
    normalized["sourceIds"] = sorted(
        {
            str(value).strip()
            for value in normalized.get("sourceIds", [])
            if str(value).strip()
        }
    )
    normalized["sourceType"] = normalized.get("sourceType") or "modelled"
    if normalized["sourceType"] not in SOURCE_RANK:
        raise ValueError(f"unsupported power-plant source type: {normalized['sourceType']}")
    normalized["valueKind"] = normalized.get("valueKind") or (
        normalized.get("capacityValueKind")
        if normalized.get("capacityMw") is not None
        else "observed"
    )
    normalized["capacityValueKind"] = normalized.get("capacityValueKind") or (
        normalized["valueKind"] if normalized.get("capacityMw") is not None else "unavailable"
    )
    if normalized.get("annualGenerationGwh") is not None:
        normalized["generationValueKind"] = normalized.get("generationValueKind") or normalized["valueKind"]

    fuels = {
        str(value).strip()
        for value in [normalized.get("secondaryFuel"), *(normalized.get("secondaryFuels") or [])]
        if value is not None and str(value).strip()
    }
    primary_fuel = _clean_text(normalized.get("primaryFuel"))
    if primary_fuel:
        fuels.discard(primary_fuel)
    preferred_secondary_fuel = _clean_text(normalized.get("secondaryFuel"))
    normalized["primaryFuel"] = primary_fuel
    normalized["secondaryFuels"] = sorted(fuels)
    normalized["secondaryFuel"] = (
        preferred_secondary_fuel
        if preferred_secondary_fuel in fuels
        else sorted(fuels)[0] if fuels else None
    )

    coordinates = normalized.get("coordinates")
    if coordinates is not None:
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
            raise ValueError("power-plant coordinates must contain longitude and latitude")
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
        if (
            not math.isfinite(longitude)
            or not math.isfinite(latitude)
            or not -180 <= longitude <= 180
            or not -90 <= latitude <= 90
        ):
            raise ValueError("power-plant coordinates must be finite WGS84 coordinates")
        normalized["coordinates"] = [longitude, latitude]
        normalized["locationPrecision"] = normalized.get("locationPrecision") or "exact"
    else:
        normalized["locationPrecision"] = normalized.get("locationPrecision") or "region_centroid"
    normalized["geographyId"] = normalized.get("geographyId") or normalized.get("country") or "UNASSIGNED"
    if geographies:
        normalized["geographyId"] = assign_asset_geography(normalized, geographies)

    aliases = {
        str(value).strip()
        for value in [
            *(normalized.get("aliases") or []),
            normalized.get("name"),
            normalized.get("plantName"),
        ]
        if value is not None and str(value).strip()
    }
    normalized["aliases"] = sorted(aliases)
    normalized["evidence"] = sorted(
        [deepcopy(item) for item in normalized.get("evidence", []) if isinstance(item, dict)],
        key=_stable_json,
    )
    normalized.pop("subtype", None)
    return normalized


def _shared_namespace_id(
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    namespaces: set[str] | None = None,
    exclude_namespaces: set[str] | None = None,
) -> bool:
    first_ids = first.get("externalIds") or {}
    second_ids = second.get("externalIds") or {}
    for namespace, value in first_ids.items():
        normalized_namespace = _key(namespace).replace(" ", "")
        if namespaces is not None and normalized_namespace not in namespaces:
            continue
        if exclude_namespaces is not None and normalized_namespace in exclude_namespaces:
            continue
        if namespace in second_ids and str(value).strip() == str(second_ids[namespace]).strip():
            return True
    return False


def _unit_record(record: dict[str, Any]) -> bool:
    return _present(record.get("unitId"))


def _shared_record_identity(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_unit = _unit_record(first)
    second_unit = _unit_record(second)
    if first_unit != second_unit:
        return False
    if first_unit:
        return _shared_namespace_id(
            first,
            second,
            namespaces=_UNIT_ID_NAMESPACES,
        )
    return _shared_namespace_id(first, second)


def _country_key(record: dict[str, Any]) -> str:
    return _key(record.get("countryIso3") or record.get("country"))


def _central_capacity(record: dict[str, Any]) -> float | None:
    capacity = record.get("capacityMw")
    return float(capacity["central"]) if isinstance(capacity, dict) else None


def _strong_fuzzy_duplicate(first: dict[str, Any], second: dict[str, Any], aliases: dict[str, str]) -> bool:
    if _unit_record(first) != _unit_record(second):
        return False
    if _unit_record(first):
        first_ids = {
            _key(namespace).replace(" ", ""): str(value)
            for namespace, value in (first.get("externalIds") or {}).items()
            if _key(namespace).replace(" ", "") in _UNIT_ID_NAMESPACES
        }
        second_ids = {
            _key(namespace).replace(" ", ""): str(value)
            for namespace, value in (second.get("externalIds") or {}).items()
            if _key(namespace).replace(" ", "") in _UNIT_ID_NAMESPACES
        }
        if any(
            first_ids[namespace] != second_ids[namespace]
            for namespace in first_ids.keys() & second_ids.keys()
        ):
            return False
    country = _country_key(first)
    if not country or country != _country_key(second):
        return False
    first_operator = _normalized_text(first.get("operator"), aliases)
    second_operator = _normalized_text(second.get("operator"), aliases)
    if not first_operator or first_operator != second_operator:
        return False
    first_coordinates = first.get("coordinates")
    second_coordinates = second.get("coordinates")
    if not first_coordinates or not second_coordinates or _distance_km(first_coordinates, second_coordinates) > 5:
        return False
    first_capacity = _central_capacity(first)
    second_capacity = _central_capacity(second)
    if first_capacity is None or second_capacity is None:
        return False
    if first_capacity == 0 or second_capacity == 0:
        if first_capacity != second_capacity:
            return False
    elif not 0.9 <= first_capacity / second_capacity <= 1.1:
        return False
    first_name = first.get("plantName") or first.get("name")
    second_name = second.get("plantName") or second.get("name")
    first_tokens = _name_tokens(first_name, aliases)
    second_tokens = _name_tokens(second_name, aliases)
    if not first_tokens or not second_tokens:
        return False
    similarity = len(first_tokens & second_tokens) / len(first_tokens | second_tokens)
    return similarity >= 0.8


def _field_value_kind(record: dict[str, Any], field: str) -> str | None:
    kind_field = _FIELD_KIND_NAMES.get(field)
    if kind_field:
        return record.get(kind_field) or record.get("valueKind")
    return record.get("valueKind")


def _field_preference(record: dict[str, Any], field: str) -> tuple[int, int, int, str]:
    value_kind = _field_value_kind(record, field)
    value_rank = _VALUE_KIND_RANK.get(str(value_kind), 0) if field in _FIELD_KIND_NAMES else 0
    source_rank = SOURCE_RANK.get(record.get("sourceType"), 0)
    precision_rank = {"region_centroid": 0, "city_centroid": 1, "exact": 2}.get(
        record.get("locationPrecision"), -1
    )
    return (value_rank, source_rank, precision_rank, _stable_json(record))


def _selected_record(records: list[dict[str, Any]], field: str) -> dict[str, Any] | None:
    candidates = [record for record in records if _present(record.get(field))]
    return max(candidates, key=lambda record: _field_preference(record, field)) if candidates else None


def _combine_external_ids(records: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    values: dict[str, set[str]] = {}
    for record in records:
        for namespace, external_id in (record.get("externalIds") or {}).items():
            values.setdefault(namespace, set()).add(str(external_id))
    selected: dict[str, str] = {}
    aliases: dict[str, list[str]] = {}
    for namespace, external_ids in sorted(values.items()):
        if len(external_ids) == 1:
            selected[namespace] = next(iter(external_ids))
            continue
        candidates = [
            record
            for record in records
            if str((record.get("externalIds") or {}).get(namespace, "")) in external_ids
        ]
        preferred = max(candidates, key=lambda record: _field_preference(record, "externalIds"))
        selected[namespace] = str(preferred["externalIds"][namespace])
        aliases[namespace] = sorted(external_ids)
    return selected, aliases


def _merge_record_cluster(records: list[dict[str, Any]]) -> dict[str, Any]:
    fields = sorted(
        {field for record in records for field in record}
        - {
            "aliases",
            "evidence",
            "externalIdAliases",
            "externalIds",
            "fieldProvenance",
            "sourceIds",
        }
    )
    merged: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    for field in fields:
        selected = _selected_record(records, field)
        if selected is None:
            continue
        merged[field] = deepcopy(selected[field])
        provenance[field] = {
            "sourceType": selected.get("sourceType"),
            "sourceIds": sorted(selected.get("sourceIds") or []),
            "valueKind": _field_value_kind(selected, field),
        }

    merged["sourceIds"] = sorted(
        {
            source_id
            for record in records
            for source_id in record.get("sourceIds", [])
        }
    )
    external_ids, external_id_aliases = _combine_external_ids(records)
    merged["externalIds"] = external_ids
    if external_id_aliases:
        merged["externalIdAliases"] = external_id_aliases
    merged["aliases"] = sorted({alias for record in records for alias in record.get("aliases", [])})
    evidence_by_json = {
        _stable_json(claim): deepcopy(claim)
        for record in records
        for claim in record.get("evidence", [])
    }
    merged["evidence"] = sorted(
        evidence_by_json.values(),
        key=lambda claim: (
            str(claim.get("id", "")),
            str(claim.get("sourceId", "")),
            _stable_json(claim),
        ),
    )
    merged["fieldProvenance"] = dict(sorted(provenance.items()))

    # The value-kind companion must describe the source selected for its metric.
    for metric_field, kind_field in _FIELD_KIND_NAMES.items():
        selected = _selected_record(records, metric_field)
        if selected is not None:
            merged[kind_field] = selected.get(kind_field) or selected.get("valueKind")

    all_secondary_fuels = {
        fuel
        for record in records
        for fuel in [record.get("secondaryFuel"), *(record.get("secondaryFuels") or [])]
        if fuel
    }
    primary_fuel = merged.get("primaryFuel")
    if primary_fuel:
        all_secondary_fuels.discard(primary_fuel)
    preferred_secondary_fuel = merged.get("secondaryFuel")
    merged["secondaryFuels"] = sorted(all_secondary_fuels)
    merged["secondaryFuel"] = (
        preferred_secondary_fuel
        if preferred_secondary_fuel in all_secondary_fuels
        else sorted(all_secondary_fuels)[0] if all_secondary_fuels else None
    )
    return merged


def _clusters(records: list[dict[str, Any]], aliases: dict[str, str]) -> list[list[dict[str, Any]]]:
    groups = _DisjointSet.create(len(records))
    for first_index, first in enumerate(records):
        for second_index in range(first_index + 1, len(records)):
            second = records[second_index]
            if _shared_record_identity(first, second) or _strong_fuzzy_duplicate(first, second, aliases):
                groups.union(first_index, second_index)
    clustered: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(records):
        clustered.setdefault(groups.find(index), []).append(record)
    return [clustered[index] for index in sorted(clustered)]


def _same_plant(first: dict[str, Any], second: dict[str, Any], aliases: dict[str, str]) -> bool:
    if _shared_namespace_id(first, second, exclude_namespaces=_UNIT_ID_NAMESPACES):
        return True
    if first.get("plantId") and first.get("plantId") == second.get("plantId"):
        return True
    if _country_key(first) != _country_key(second):
        return False
    first_name = _normalized_text(first.get("plantName") or first.get("name"), aliases)
    second_name = _normalized_text(second.get("plantName") or second.get("name"), aliases)
    if not first_name or first_name != second_name:
        return False
    first_operator = _normalized_text(first.get("operator"), aliases)
    second_operator = _normalized_text(second.get("operator"), aliases)
    if not first_operator or first_operator != second_operator:
        return False
    first_coordinates = first.get("coordinates")
    second_coordinates = second.get("coordinates")
    return bool(
        first_coordinates
        and second_coordinates
        and _distance_km(first_coordinates, second_coordinates) <= 5
    )


def _plant_clusters(records: list[dict[str, Any]], aliases: dict[str, str]) -> list[list[dict[str, Any]]]:
    groups = _DisjointSet.create(len(records))
    for first_index, first in enumerate(records):
        for second_index in range(first_index + 1, len(records)):
            if _same_plant(first, records[second_index], aliases):
                groups.union(first_index, second_index)
    clustered: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(records):
        clustered.setdefault(groups.find(index), []).append(record)
    return [clustered[index] for index in sorted(clustered)]


def _sum_ranges(records: Iterable[dict[str, Any]]) -> dict[str, float]:
    total = {"low": 0.0, "central": 0.0, "high": 0.0}
    for record in records:
        capacity = record.get("capacityMw")
        if capacity:
            for part in total:
                total[part] += float(capacity[part])
    return total


def _capacity_by_technology(records: Iterable[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for record in records:
        capacity = record.get("capacityMw")
        if capacity:
            technology = record.get("technology") or "other"
            totals[technology] = totals.get(technology, 0.0) + float(capacity["central"])
    return dict(sorted(totals.items()))


def _summarize_plant(records: list[dict[str, Any]]) -> dict[str, Any]:
    units = [record for record in records if _unit_record(record)]
    counting_records = units if units else records
    operating = [
        record
        for record in counting_records
        if record.get("lifecycle") in _OPERATING_LIFECYCLES
    ]
    planned = [
        record
        for record in counting_records
        if record.get("lifecycle") in _PLANNED_LIFECYCLES
    ]
    name_record = _selected_record(records, "plantName") or _selected_record(records, "name")
    id_record = _selected_record(records, "plantId") or _selected_record(records, "id")
    assert name_record is not None and id_record is not None
    lifecycle_counts: dict[str, int] = {}
    for record in counting_records:
        lifecycle = record.get("lifecycle") or "unknown"
        lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + 1
    external_ids, external_id_aliases = _combine_external_ids(records)
    summary = {
        "id": id_record.get("plantId") or id_record["id"],
        "name": name_record.get("plantName") or name_record["name"],
        "country": (_selected_record(records, "country") or {}).get("country"),
        "geographyId": (_selected_record(records, "geographyId") or {}).get("geographyId"),
        "coordinates": deepcopy((_selected_record(records, "coordinates") or {}).get("coordinates")),
        "unitCount": len(units),
        "recordCount": len(records),
        "technologies": sorted({record.get("technology") or "other" for record in counting_records}),
        "lifecycleCounts": dict(sorted(lifecycle_counts.items())),
        "operatingCapacityMw": _sum_ranges(operating),
        "plannedCapacityMw": _sum_ranges(planned),
        "operatingCapacityMwByTechnology": _capacity_by_technology(operating),
        "plannedCapacityMwByTechnology": _capacity_by_technology(planned),
        "sourceIds": sorted(
            {
                source_id
                for record in records
                for source_id in record.get("sourceIds", [])
            }
        ),
        "externalIds": external_ids,
        "aliases": sorted({alias for record in records for alias in record.get("aliases", [])}),
        "recordIds": sorted(record["id"] for record in records),
        "unitIds": sorted(record["unitId"] for record in units),
    }
    if external_id_aliases:
        summary["externalIdAliases"] = external_id_aliases
    return summary


def canonicalize_power_plants(
    records: list[dict[str, Any]],
    *,
    geographies: list[dict] | None = None,
    aliases: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Canonicalize source plant records while preserving unit-level evidence.

    ``records`` contains canonical source rows, ``units`` is the addressable unit
    subset, and ``plants`` contains capacity summaries. Plant-only source rows are
    retained as evidence but are not added to a summary's capacity when unit rows
    exist, preventing plant/unit double counting.
    """

    alias_map = {_key(key): _key(value) for key, value in (aliases or {}).items()}
    normalized = [_normalize_record(record, geographies) for record in records]
    normalized.sort(key=lambda record: (str(record.get("id", "")), _stable_json(record)))
    canonical_records = [
        _merge_record_cluster(cluster)
        for cluster in _clusters(normalized, alias_map)
    ]
    canonical_records.sort(key=lambda record: str(record.get("id", "")))
    plants = [
        _summarize_plant(cluster)
        for cluster in _plant_clusters(canonical_records, alias_map)
    ]
    plants.sort(key=lambda plant: str(plant["id"]))
    units = sorted(
        [record for record in canonical_records if _unit_record(record)],
        key=lambda record: str(record.get("unitId", "")),
    )
    return {"plants": plants, "units": units, "records": canonical_records}
