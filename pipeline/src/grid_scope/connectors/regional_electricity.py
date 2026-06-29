from __future__ import annotations

import csv
from datetime import date
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


ENERGY_FIELDS = (
    "demandGwh",
    "localGenerationGwh",
    "netInterchangeGwh",
    "observedUnmetDemandGwh",
)
POWER_FIELDS = ("peakDemandMw", "installedCapacityMw")
SCALAR_FIELDS = ENERGY_FIELDS + POWER_FIELDS

SOURCE_RANK = {
    "official_verified": 4,
    "curated_official": 4,
    "research_verified": 3,
    "community_mapped": 2,
    "modelled": 1,
}

_ENERGY_FACTORS_TO_GWH = {"MWh": 0.001, "GWh": 1.0, "TWh": 1000.0}
_POWER_FACTORS_TO_MW = {"MW": 1.0}
_GENERATION_TECHNOLOGIES = {
    "solar", "wind", "hydro", "nuclear", "gas", "coal", "oil",
    "biomass", "geothermal", "other",
}


def normalize_metric_value(value: Any, *, unit: str, dimension: str) -> float | None:
    """Convert supported public-source units to GWh or MW without inference."""

    normalized_unit = str(unit).strip()
    if dimension == "energy":
        factors = _ENERGY_FACTORS_TO_GWH
        incompatible = _POWER_FACTORS_TO_MW
    elif dimension == "power":
        factors = _POWER_FACTORS_TO_MW
        incompatible = _ENERGY_FACTORS_TO_GWH
    else:
        raise ValueError(f"unsupported metric dimension: {dimension}")
    if normalized_unit in incompatible:
        raise ValueError(f"{dimension} metric is incompatible with unit {normalized_unit}")
    if (value is None or str(value).strip() == "") and not normalized_unit:
        return None
    if normalized_unit not in factors:
        raise ValueError(f"unsupported {dimension} unit: {normalized_unit or '<missing>'}")
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(str(value).replace(",", ""))
    except ValueError as error:
        raise ValueError(f"invalid {dimension} value: {value}") from error
    if not math.isfinite(number):
        raise ValueError(f"invalid {dimension} value: {value}")
    # Net interchange is signed; callers validate nonnegative-only fields.
    return number * factors[normalized_unit]


def validate_region_mapping(
    mapping: Mapping[str, str],
    *,
    active_geography_ids: Iterable[str],
    observed_source_codes: Iterable[str] = (),
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_code, raw_geography_id in mapping.items():
        code = str(raw_code).strip()
        geography_id = str(raw_geography_id).strip()
        if not code or not geography_id:
            raise ValueError("region mappings require non-empty source codes and geography IDs")
        if code in normalized and normalized[code] != geography_id:
            raise ValueError(f"source region code has conflicting mappings: {code}")
        normalized[code] = geography_id
    active = {str(value).strip() for value in active_geography_ids}
    inactive = sorted(set(normalized.values()) - active)
    if inactive:
        raise ValueError(f"inactive geography IDs in region mapping: {', '.join(inactive)}")
    unknown = sorted({str(code).strip() for code in observed_source_codes} - set(normalized))
    if unknown:
        raise ValueError(f"unmapped source region codes: {', '.join(unknown)}")
    return dict(sorted(normalized.items()))


def load_region_mapping_csv(
    path: Path | str,
    *,
    active_geography_ids: Iterable[str],
) -> dict[str, str]:
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    mapping: dict[str, str] = {}
    for index, row in enumerate(rows, start=2):
        code = str(row.get("source_region_code") or "").strip()
        geography_id = str(row.get("geography_id") or "").strip()
        if not code or not geography_id:
            raise ValueError(f"region mapping row {index} lacks source_region_code or geography_id")
        if code in mapping:
            raise ValueError(f"duplicate source region code in mapping: {code}")
        mapping[code] = geography_id
    return validate_region_mapping(mapping, active_geography_ids=active_geography_ids)


def _require_public_lineage(row: Mapping[str, Any], *, row_number: int) -> None:
    required = (
        "source_id",
        "source_record_id",
        "source_url",
        "licence",
        "updated_at",
        "observation_date",
        "value_kind",
        "method_id",
    )
    missing = [field for field in required if not str(row.get(field) or "").strip()]
    if missing:
        raise ValueError(f"regional electricity row {row_number} lacks {', '.join(missing)}")
    source_url = str(row["source_url"]).strip()
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"regional electricity row {row_number} requires a public source URL")
    licence = str(row["licence"]).strip()
    if not licence:
        raise ValueError(f"regional electricity row {row_number} requires a licence")
    if any(term in licence.lower() for term in ("private", "proprietary", "restricted", "no redistribution")):
        raise ValueError(f"regional electricity row {row_number} licence is not redistributable")


def _iso_date(value: str, *, label: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValueError(f"invalid {label}: {value}") from error


def _nonnegative(value: float | None, *, field: str, row_number: int) -> float | None:
    if value is not None and value < 0:
        raise ValueError(f"regional electricity row {row_number} has negative {field}")
    return value


def _mix(raw: str, *, row_number: int) -> tuple[dict[str, float], dict[str, dict[str, str]]]:
    if not raw.strip():
        return {}, {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"regional electricity row {row_number} has invalid generation mix JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"regional electricity row {row_number} generation mix must be an object")
    result: dict[str, float] = {}
    units: dict[str, dict[str, str]] = {}
    for technology, observation in sorted(payload.items()):
        technology = str(technology).strip().lower()
        if technology not in _GENERATION_TECHNOLOGIES:
            raise ValueError(f"unsupported generation-mix technology: {technology}")
        if not isinstance(observation, dict):
            raise ValueError(f"generation mix {technology} must include value and unit")
        unit = str(observation.get("unit") or "").strip()
        value = normalize_metric_value(observation.get("value"), unit=unit, dimension="energy")
        if value is not None:
            result[technology] = _nonnegative(value, field=f"generationMix.{technology}", row_number=row_number)  # type: ignore[assignment]
        units[f"generationMixGwh.{technology}"] = {"sourceUnit": unit, "canonicalUnit": "GWh"}
    return result, units


def load_curated_regional_observations(
    path: Path | str,
    *,
    region_mapping: Mapping[str, str],
    active_geography_ids: Iterable[str],
) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    observed_codes = {str(row.get("source_region_code") or "").strip() for row in rows}
    mapping = validate_region_mapping(
        region_mapping,
        active_geography_ids=active_geography_ids,
        observed_source_codes=observed_codes,
    )
    records: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=2):
        _require_public_lineage(row, row_number=row_number)
        source_code = str(row["source_region_code"]).strip()
        country_iso3 = str(row.get("country_iso3") or "").strip().upper()
        if re.fullmatch(r"[A-Z]{3}", country_iso3) is None:
            raise ValueError(f"regional electricity row {row_number} has invalid country ISO3")
        try:
            year = int(str(row.get("year") or ""))
        except ValueError as error:
            raise ValueError(f"regional electricity row {row_number} has invalid year") from error
        if not 1900 <= year <= 2100:
            raise ValueError(f"regional electricity row {row_number} has invalid year: {year}")

        demand = normalize_metric_value(row.get("demand_value"), unit=str(row.get("demand_unit") or ""), dimension="energy")
        generation = normalize_metric_value(row.get("generation_value"), unit=str(row.get("generation_unit") or ""), dimension="energy")
        peak = normalize_metric_value(row.get("peak_value"), unit=str(row.get("peak_unit") or ""), dimension="power")
        interchange = normalize_metric_value(row.get("net_interchange_value"), unit=str(row.get("net_interchange_unit") or ""), dimension="energy")
        unmet = normalize_metric_value(row.get("observed_unmet_demand_value"), unit=str(row.get("observed_unmet_demand_unit") or ""), dimension="energy")
        mix, mix_units = _mix(str(row.get("generation_mix_json") or ""), row_number=row_number)
        updated_at = _iso_date(str(row["updated_at"]).strip(), label="updated_at")
        observation_date = _iso_date(str(row["observation_date"]).strip(), label="observation_date")
        value_kind = str(row["value_kind"]).strip()
        if value_kind not in {"observed", "reported", "estimated", "inherited"}:
            raise ValueError(
                f"regional electricity row {row_number} has unsupported value kind: {value_kind}"
            )
        unit_metadata = {
            "demandGwh": {"sourceUnit": str(row.get("demand_unit") or ""), "canonicalUnit": "GWh"},
            "localGenerationGwh": {"sourceUnit": str(row.get("generation_unit") or ""), "canonicalUnit": "GWh"},
            "peakDemandMw": {"sourceUnit": str(row.get("peak_unit") or ""), "canonicalUnit": "MW"},
            "netInterchangeGwh": {"sourceUnit": str(row.get("net_interchange_unit") or ""), "canonicalUnit": "GWh"},
            "observedUnmetDemandGwh": {"sourceUnit": str(row.get("observed_unmet_demand_unit") or ""), "canonicalUnit": "GWh"},
            **mix_units,
        }
        records.append({
            "geographyId": mapping[source_code],
            "geographyLevel": "admin_1",
            "countryIso3": country_iso3,
            "year": year,
            "period": "annual",
            "demandGwh": _nonnegative(demand, field="demand", row_number=row_number),
            "localGenerationGwh": _nonnegative(generation, field="generation", row_number=row_number),
            "peakDemandMw": _nonnegative(peak, field="peak demand", row_number=row_number),
            "netInterchangeGwh": interchange,
            "observedUnmetDemandGwh": _nonnegative(unmet, field="observed unmet demand", row_number=row_number),
            "installedCapacityMw": None,
            "generationMixGwh": mix,
            "sourceIds": [str(row["source_id"]).strip()],
            "sourceId": str(row["source_id"]).strip(),
            "sourceRecordId": str(row["source_record_id"]).strip(),
            "sourceType": "official_verified",
            "sourceUrl": str(row["source_url"]).strip(),
            "licence": str(row["licence"]).strip(),
            "updatedAt": updated_at,
            "observationDate": observation_date,
            "freshnessDays": (date.fromisoformat(updated_at) - date.fromisoformat(observation_date)).days,
            "valueKind": value_kind,
            "methodId": str(row["method_id"]).strip(),
            "unitMetadata": unit_metadata,
        })
    _reject_duplicate_observation_keys(records)
    return sorted(records, key=_observation_sort_key)


def _observation_sort_key(record: Mapping[str, Any]) -> tuple[str, int, str, str]:
    return (
        str(record.get("geographyId") or ""),
        int(record.get("year") or 0),
        str(record.get("sourceId") or ""),
        str(record.get("sourceRecordId") or ""),
    )


def _reject_duplicate_observation_keys(records: Iterable[Mapping[str, Any]]) -> None:
    seen: set[tuple[str, int, str, str]] = set()
    for record in records:
        key = _observation_sort_key(record)
        if key in seen:
            raise ValueError(f"duplicate observation key: {key}")
        seen.add(key)


def _provenance(record: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    return {
        "sourceId": record.get("sourceId"),
        "sourceRecordId": record.get("sourceRecordId"),
        "sourceType": record.get("sourceType"),
        "sourceUrl": record.get("sourceUrl"),
        "licence": record.get("licence"),
        "updatedAt": record.get("updatedAt"),
        "observationDate": record.get("observationDate"),
        "freshnessDays": record.get("freshnessDays"),
        "valueKind": record.get("valueKind"),
        "methodId": record.get("methodId"),
        "unit": (record.get("unitMetadata") or {}).get(field),
        "sourceSeries": (record.get("sourceSeries") or {}).get(field),
    }


def merge_regional_observations(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    materialized = [dict(record) for record in records]
    if any(record.get("geographyLevel") != "admin_1" for record in materialized):
        raise ValueError("only ADM1 observations can be merged; country controls are separate")
    _reject_duplicate_observation_keys(materialized)
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for record in materialized:
        source_type = str(record.get("sourceType") or "")
        if source_type not in SOURCE_RANK:
            raise ValueError(f"unsupported regional electricity source type: {source_type}")
        key = (
            str(record.get("geographyId") or ""),
            int(record.get("year") or 0),
            str(record.get("period") or "annual"),
        )
        grouped.setdefault(key, []).append(record)

    output: list[dict[str, Any]] = []
    for key in sorted(grouped):
        evidence = sorted(
            grouped[key],
            key=lambda record: (-SOURCE_RANK[str(record["sourceType"])], _observation_sort_key(record)),
        )
        countries = {str(record.get("countryIso3") or "") for record in evidence}
        if len(countries) != 1 or "" in countries:
            raise ValueError(f"inconsistent country ISO3 values for {key[0]} {key[1]}")
        best = evidence[0]
        merged: dict[str, Any] = {
            "geographyId": key[0],
            "geographyLevel": "admin_1",
            "countryIso3": best.get("countryIso3"),
            "year": key[1],
            "period": key[2],
            "generationMixGwh": {},
            "fieldProvenance": {},
            "unitMetadata": {},
        }
        for field in SCALAR_FIELDS:
            candidates = [record for record in evidence if record.get(field) is not None]
            if not candidates:
                merged[field] = None
                continue
            top_rank = SOURCE_RANK[str(candidates[0]["sourceType"])]
            top = [record for record in candidates if SOURCE_RANK[str(record["sourceType"])] == top_rank]
            distinct = {float(record[field]) for record in top}
            if top_rank == SOURCE_RANK["official_verified"] and len(distinct) > 1:
                raise ValueError(f"conflicting official values for {key[0]} {key[1]} {field}")
            selected = top[0]
            merged[field] = selected[field]
            merged["fieldProvenance"][field] = _provenance(selected, field=field)
            unit = (selected.get("unitMetadata") or {}).get(field)
            if unit is not None:
                merged["unitMetadata"][field] = unit

        technologies = sorted({
            technology
            for record in evidence
            for technology in (record.get("generationMixGwh") or {})
        })
        for technology in technologies:
            candidates = [
                record for record in evidence
                if (record.get("generationMixGwh") or {}).get(technology) is not None
            ]
            top_rank = SOURCE_RANK[str(candidates[0]["sourceType"])]
            top = [record for record in candidates if SOURCE_RANK[str(record["sourceType"])] == top_rank]
            distinct = {float(record["generationMixGwh"][technology]) for record in top}
            if top_rank == SOURCE_RANK["official_verified"] and len(distinct) > 1:
                raise ValueError(
                    f"conflicting official values for {key[0]} {key[1]} generationMixGwh.{technology}"
                )
            selected = top[0]
            merged["generationMixGwh"][technology] = selected["generationMixGwh"][technology]
            mix_field = f"generationMixGwh.{technology}"
            merged["fieldProvenance"][mix_field] = _provenance(selected, field=mix_field)
            unit = (selected.get("unitMetadata") or {}).get(mix_field)
            if unit is not None:
                merged["unitMetadata"][mix_field] = unit

        merged["sourceIds"] = sorted({
            str(source_id)
            for record in evidence
            for source_id in (record.get("sourceIds") or [record.get("sourceId")])
            if source_id
        })
        # Top-level lineage describes the highest-ranked observation; field-level
        # lineage is authoritative for mixed official/modelled records.
        for field in (
            "sourceId", "sourceType", "sourceUrl", "licence", "updatedAt",
            "observationDate", "freshnessDays", "valueKind", "methodId",
        ):
            merged[field] = best.get(field)
        output.append(merged)
    return output
