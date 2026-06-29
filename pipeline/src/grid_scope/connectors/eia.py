from __future__ import annotations

from datetime import UTC, date, datetime
import json
import re
from typing import Any, Iterable, Mapping
from urllib.parse import quote, quote_plus, urljoin, urlparse

import httpx

from grid_scope.config import EIA_API_KEY, EIA_API_V2_URL
from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.connectors.regional_electricity import normalize_metric_value, validate_region_mapping
from grid_scope.models import ConnectorState


EIA_SOURCE_ID = "eia-api-v2"
EIA_SOURCE_URL = "https://www.eia.gov/opendata/"
EIA_LICENCE = "US-PUBLIC-DOMAIN"

EIA_ROUTE_PATHS = {
    "sales": "electricity/retail-sales/data/",
    "generation": "electricity/electric-power-operational-data/data/",
    "capability": "electricity/state-electricity-profiles/capability/data/",
    "interchange": "electricity/rto/region-data/data/",
}

_EIA_ROUTE_QUERIES: dict[str, dict[str, str]] = {
    "sales": {
        "frequency": "annual",
        "data[0]": "sales",
        "facets[sectorid][]": "ALL",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
    },
    "generation": {
        "frequency": "annual",
        "data[0]": "generation",
        "facets[sectorid][]": "99",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
    },
    "capability": {
        "frequency": "annual",
        "data[0]": "capability",
        "facets[producerTypeId][]": "ALL",
        "facets[fuelTypeId][]": "ALL",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
    },
}


def build_eia_route_query(
    route_id: str, *, state_codes: Iterable[str] = ()
) -> dict[str, Any]:
    """Build a reproducible annual EIA query for a supported state route."""

    if route_id not in _EIA_ROUTE_QUERIES:
        raise ValueError(f"EIA route query is unsupported: {route_id}")
    query: dict[str, Any] = dict(_EIA_ROUTE_QUERIES[route_id])
    states = sorted({str(code).strip().upper() for code in state_codes if str(code).strip()})
    if states:
        facet = {
            "sales": "facets[stateid][]",
            "generation": "facets[location][]",
            "capability": "facets[stateId][]",
        }[route_id]
        query[facet] = states[0] if len(states) == 1 else states
    return query


def _validate_eia_route_query(route_id: str, params: Mapping[str, Any]) -> None:
    expected = build_eia_route_query(route_id)
    mismatches = [key for key, value in expected.items() if params.get(key) != value]
    if mismatches:
        raise ValueError(
            f"EIA {route_id} fetch requires a validated annual route query; "
            f"invalid or missing: {', '.join(sorted(mismatches))}"
        )


_SECRET_KEYS = frozenset({"api_key", "apikey", "token", "authorization"})


def _redact_text(value: str, secrets: Iterable[str]) -> str:
    redacted = value
    variants = {
        variant
        for secret in secrets
        if secret
        for variant in (secret, quote(secret, safe=""), quote_plus(secret))
        if variant
    }
    for variant in sorted(variants, key=len, reverse=True):
        redacted = redacted.replace(variant, "[redacted]")
    return redacted


def _scrub_secrets(value: Any, *, secrets: Iterable[str] = ()) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _scrub_secrets(item, secrets=secrets)
            for key, item in value.items()
            if str(key).strip().lower() not in _SECRET_KEYS
        }
    if isinstance(value, list):
        return [_scrub_secrets(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        return _redact_text(value, secrets)
    return value

# EIA operational-data fuel IDs. Aggregate codes are deliberately mapped to
# ``other`` only as a fallback; hierarchy selection below removes them whenever
# a more specific component is present for the same geography/year/sector.
_FUEL_TECHNOLOGY = {
    "FOS": "other",  # aggregate: all fossil fuels
    "REN": "other",  # aggregate: all renewables
    "AOR": "other",  # all other renewables; only explicit "all renewables" is aggregate
    "COW": "coal",   # aggregate: coal and coal grades
    "ANT": "coal",
    "BIT": "coal",
    "COL": "coal",
    "LIG": "coal",
    "SUB": "coal",
    "WC": "coal",
    "GAS": "gas",  # aggregate: gaseous fossil fuels
    "NG": "gas",
    "BFG": "gas",
    "OG": "gas",
    "OOG": "gas",
    "DFO": "oil",
    "OIL": "oil",
    "JF": "oil",
    "KER": "oil",
    "PC": "oil",
    "PEL": "oil",  # aggregate: petroleum liquids
    "PET": "oil",
    "PG": "oil",
    "RFO": "oil",
    "WO": "oil",
    "SUN": "solar",
    "DPV": "solar",
    "WND": "wind",
    "HYC": "hydro",
    "HPS": "hydro",
    "GEO": "geothermal",
    "NUC": "nuclear",
    "BIO": "biomass",  # aggregate: biomass components
    "AB": "biomass",
    "BLQ": "biomass",
    "MSW": "biomass",
    "OBG": "biomass",
    "SLW": "biomass",
    "WDL": "biomass",
    "WDS": "biomass",
    "WWW": "biomass",
}

_FUEL_CHILDREN = {
    "FOS": frozenset({"COW", "GAS", "PET"}),
    "COW": frozenset({"ANT", "BIT", "COL", "LIG", "SUB", "WC"}),
    "GAS": frozenset({"NG", "BFG", "OG", "OOG"}),
    "PET": frozenset({"PEL", "PC", "PG"}),
    "PEL": frozenset({"DFO", "JF", "KER", "RFO", "WO"}),
    "REN": frozenset({"AOR", "SUN", "WND", "HYC", "HPS", "GEO", "BIO"}),
    "BIO": frozenset({"AB", "BLQ", "MSW", "OBG", "SLW", "WDL", "WDS"}),
}

_AOR_AGGREGATE_CHILDREN = frozenset({
    "SUN", "WND", "HYC", "HPS", "GEO", "BIO",
    "AB", "BLQ", "MSW", "OBG", "SLW", "WDL", "WDS",
})

# EIA publishes pumped-storage generation net of pumping load. Its annual HPS
# value can therefore be negative; ordinary generation fuels and ALL totals may not.
_NET_STORAGE_FUEL_CODES = frozenset({"HPS"})

_SYNTHETIC_SERIES = {
    "sales": ("demandGwh", "energy"),
    "demand": ("demandGwh", "energy"),
    "generation": ("localGenerationGwh", "energy"),
    "net-generation": ("localGenerationGwh", "energy"),
    "capability": ("installedCapacityMw", "power"),
    "capacity": ("installedCapacityMw", "power"),
    "peak-demand": ("peakDemandMw", "power"),
    "net-interchange": ("netInterchangeGwh", "energy"),
    "unmet-demand": ("observedUnmetDemandGwh", "energy"),
}


def _get(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _response(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], list[dict[str, Any]]]:
    response = payload.get("response")
    if not isinstance(response, Mapping) or not isinstance(response.get("data"), list):
        raise ValueError("unexpected EIA API v2 response: response.data is required")
    rows = response["data"]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("unexpected EIA API v2 response row")
    return response, rows


def _annual_response(
    payload: Mapping[str, Any], *, allow_preaggregated: bool = False
) -> tuple[Mapping[str, Any], list[dict[str, Any]]]:
    response, rows = _response(payload)
    frequency = str(response.get("frequency") or "").lower()
    if allow_preaggregated and rows and all(row.get("preAggregatedAnnual") is True for row in rows):
        return response, rows
    if frequency not in {"annual", "yearly"}:
        raise ValueError(
            f"EIA regional electricity requires annual energy observations, got {frequency or 'missing'}"
        )
    return response, rows


def _series(row: Mapping[str, Any]) -> str:
    value = _get(row, "series", "seriesId", "series_id", "_series")
    return str(value or "").strip().lower().replace("_", "-")


def _period(row: Mapping[str, Any]) -> int:
    raw = str(_get(row, "period", "year") or "").strip()
    try:
        year = int(raw[:4])
    except ValueError as error:
        raise ValueError(f"invalid EIA period: {raw}") from error
    if len(raw) < 4 or not 1900 <= year <= 2100:
        raise ValueError(f"invalid EIA period: {raw}")
    return year


def _route_from_payload(payload: Mapping[str, Any], explicit: str | None) -> str:
    if explicit:
        if explicit not in EIA_ROUTE_PATHS and explicit != "synthetic":
            raise ValueError(f"unsupported EIA route ID: {explicit}")
        return explicit
    _, rows = _response(payload)
    tagged = {str(row.get("_routeId") or "") for row in rows if row.get("_routeId")}
    if len(tagged) == 1:
        route = tagged.pop()
        if route in EIA_ROUTE_PATHS:
            return route
    command = str((payload.get("request") or {}).get("command") or "")
    for route, path in EIA_ROUTE_PATHS.items():
        if path.rstrip("/") in command:
            return route
    if rows and all(_series(row) for row in rows):
        return "synthetic"
    raise ValueError("EIA payload requires a recognized route ID or tagged series")


def _source_meta(
    row: Mapping[str, Any],
    *,
    facet: str,
    route_id: str,
    payload: Mapping[str, Any],
    series: str,
    unit: str,
) -> dict[str, Any]:
    response = payload.get("response") or {}
    request = payload.get("request") or {}
    metadata = {
        "routeId": route_id,
        "series": series,
        "seriesDescription": _get(row, "series-description", "seriesDescription"),
        "facet": facet,
        "sourceUnit": unit,
        "apiVersion": payload.get("apiVersion"),
        "frequency": response.get("frequency"),
        "dateFormat": response.get("dateFormat"),
        "requestCommand": request.get("command"),
    }
    raw_fuel_code = _get(row, "fueltypeid", "fuelTypeId")
    if raw_fuel_code is not None and str(raw_fuel_code).strip():
        metadata["rawFuelCode"] = str(raw_fuel_code).strip().upper()
    return metadata


def _country_iso3(geography_id: str) -> str:
    if not geography_id.startswith("US-"):
        raise ValueError(f"EIA state mapping must target a US ADM1 geography: {geography_id}")
    return "USA"


def _new_record(
    geography_id: str,
    year: int,
    *,
    source_url: str,
    retrieved_at: str | None,
    retrieved_date: date | None,
) -> dict[str, Any]:
    return {
        "geographyId": geography_id,
        "geographyLevel": "admin_1",
        "countryIso3": _country_iso3(geography_id),
        "year": year,
        "period": "annual",
        "demandGwh": None,
        "localGenerationGwh": None,
        "peakDemandMw": None,
        "netInterchangeGwh": None,
        "observedUnmetDemandGwh": None,
        "installedCapacityMw": None,
        "dependableCapacityMw": None,
        "generationMixGwh": {},
        "sourceSeries": {},
        "sourceIds": [EIA_SOURCE_ID],
        "sourceId": EIA_SOURCE_ID,
        "sourceRecordId": "",
        "sourceType": "official_verified",
        "sourceUrl": source_url,
        "licence": EIA_LICENCE,
        "updatedAt": retrieved_at,
        "observationDate": f"{year}-12-31",
        "freshnessDays": (
            (retrieved_date - date(year, 12, 31)).days if retrieved_date else None
        ),
        "valueKind": "reported",
        "methodId": "eia-api-v2-state-annual-v2",
        "unitMetadata": {},
    }


def _set_field(
    record: dict[str, Any],
    *,
    field: str,
    value: float | None,
    unit: str,
    dimension: str,
    metadata: Mapping[str, Any],
) -> None:
    if value is not None and field != "netInterchangeGwh" and value < 0:
        raise ValueError(f"EIA {field} cannot be negative")
    if record[field] is not None:
        raise ValueError(
            f"duplicate EIA value for {record['geographyId']} {record['year']} {field}"
        )
    record[field] = value
    record["sourceSeries"][field] = dict(metadata)
    record["unitMetadata"][field] = {
        "sourceUnit": unit,
        "canonicalUnit": "MW" if dimension == "power" else "GWh",
    }


def _state_code(row: Mapping[str, Any], *, route_id: str) -> str:
    if route_id == "generation":
        return str(_get(row, "location") or "").strip()
    if route_id == "capability":
        return str(_get(row, "stateId", "stateid", "stateID") or "").strip()
    return str(_get(row, "stateid", "stateId") or "").strip()


def _is_all(value: Any) -> bool:
    return str(value or "").strip().upper() in {"ALL", "TOTAL", "TSN"}


def _is_generation_sector_total(value: Any) -> bool:
    return str(value or "").strip().upper() in {"99", "ALL"}


def _is_generation_fuel_total(value: Any) -> bool:
    return str(value or "").strip().upper() in {"ALL", "TOTAL"}


def _is_sales_sector_total(value: Any) -> bool:
    return str(value or "").strip().upper() in {"ALL", "TOTAL"}


def _is_capability_producer_total(value: Any) -> bool:
    return str(value or "").strip().upper() in {"ALL", "TOTAL", "00"}


def _is_capability_fuel_total(value: Any) -> bool:
    return str(value or "").strip().upper() in {"ALL", "TOTAL", "TSN"}


def _fuel_is_aggregate(row: Mapping[str, Any], fuel: str) -> bool:
    if fuel != "AOR":
        return fuel in _FUEL_CHILDREN
    description = re.sub(
        r"[^a-z]+", " ",
        str(_get(row, "fuelTypeDescription", "fueltypedescription") or "").lower(),
    ).strip()
    return description in {"all renewable", "all renewables", "all renewable energy sources"}


def _fuel_descendants(code: str) -> frozenset[str]:
    descendants: set[str] = set()
    pending = list(_FUEL_CHILDREN.get(code, ()))
    while pending:
        child = pending.pop()
        if child in descendants:
            continue
        descendants.add(child)
        pending.extend(_FUEL_CHILDREN.get(child, ()))
    return frozenset(descendants)


def _selected_generation_row_indexes(
    rows: list[dict[str, Any]], *, states: Mapping[str, str]
) -> set[int]:
    """Select non-overlapping ALL-sector fuel leaves or aggregate fallbacks."""

    grouped: dict[tuple[str, int, str], list[tuple[int, str]]] = {}
    selected: set[int] = set()
    for index, row in enumerate(rows, start=1):
        code = _state_code(row, route_id="generation")
        if not code:
            continue
        sector = str(_get(row, "sectorid", "sectorId") or "").strip().upper()
        if not _is_generation_sector_total(sector):
            continue
        fuel = str(_get(row, "fueltypeid", "fuelTypeId") or "").strip().upper()
        if _is_generation_fuel_total(fuel):
            selected.add(index)
            continue
        grouped.setdefault((states[code], _period(row), sector or "ALL"), []).append(
            (index, fuel)
        )
    for group in grouped.values():
        present_codes = {fuel for _, fuel in group}
        rows_by_index = {index: rows[index - 1] for index, _ in group}
        for index, fuel in group:
            descendants = frozenset()
            if _fuel_is_aggregate(rows_by_index[index], fuel):
                descendants = (
                    _AOR_AGGREGATE_CHILDREN
                    if fuel == "AOR"
                    else _fuel_descendants(fuel)
                )
            if not (descendants & present_codes):
                selected.add(index)
    return selected


def normalize_eia_state(
    payload: Mapping[str, Any],
    *,
    state_mapping: Mapping[str, str],
    active_geography_ids: Iterable[str],
    balancing_authority_mapping: Mapping[str, str] | None = None,
    source_url: str = EIA_SOURCE_URL,
    retrieved_at: str | None = None,
    route_id: str | None = None,
    report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize documented EIA v2 annual state and mapped RTO observations."""

    route = _route_from_payload(payload, route_id)
    response, rows = _annual_response(payload, allow_preaggregated=route == "interchange")
    observed_state_codes = {
        _state_code(row, route_id=route)
        for row in rows
        if route != "interchange" and _state_code(row, route_id=route)
    }
    states = validate_region_mapping(
        state_mapping,
        active_geography_ids=active_geography_ids,
        observed_source_codes=observed_state_codes,
    )
    authorities = validate_region_mapping(
        balancing_authority_mapping or {},
        active_geography_ids=active_geography_ids,
    )
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("EIA source URL must be public")
    retrieved_date: date | None = None
    if retrieved_at:
        try:
            retrieved_date = date.fromisoformat(str(retrieved_at)[:10])
        except ValueError as error:
            raise ValueError(f"invalid EIA retrieval date: {retrieved_at}") from error

    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    unmapped_authorities: set[str] = set()
    unknown_fuel_codes: set[str] = set()

    # An explicit capability total outranks component rows. Components are only
    # summed below when every row is a unique, non-total producer/fuel cell.
    capability_totals: set[tuple[str, int]] = set()
    if route == "capability":
        for row in rows:
            code = _state_code(row, route_id=route)
            if code and _is_capability_producer_total(
                _get(row, "producerTypeId", "producertypeid")
            ) and _is_capability_fuel_total(
                _get(row, "fuelTypeId", "fueltypeid")
            ):
                capability_totals.add((states[code], _period(row)))

    capability_leaf_keys: set[tuple[str, int, str, str]] = set()
    generation_mix_keys: set[tuple[str, int, str]] = set()
    selected_generation_indexes = (
        _selected_generation_row_indexes(rows, states=states) if route == "generation" else set()
    )
    for index, row in enumerate(rows, start=1):
        year = _period(row)
        synthetic_series = _series(row) if route == "synthetic" else ""
        authority_value = _get(row, "respondent", "balancingAuthority", "ba")
        is_authority_row = route == "interchange" or (
            route == "synthetic" and synthetic_series == "net-interchange" and authority_value
        )
        if is_authority_row:
            if route == "interchange" and str(_get(row, "type") or "").strip().upper() != "TI":
                continue
            authority_code = str(authority_value or "").strip()
            if not authority_code:
                raise ValueError(f"EIA interchange row {index} lacks respondent")
            if authority_code not in authorities:
                unmapped_authorities.add(authority_code)
                continue
            geography_id = authorities[authority_code]
            facet = authority_code
        else:
            code = _state_code(row, route_id=route)
            if not code:
                raise ValueError(f"EIA {route} row {index} lacks a state/location facet")
            geography_id = states[code]
            facet = code

        record = grouped.setdefault(
            (geography_id, year),
            _new_record(
                geography_id,
                year,
                source_url=source_url,
                retrieved_at=retrieved_at,
                retrieved_date=retrieved_date,
            ),
        )

        if route == "sales":
            if not _is_sales_sector_total(_get(row, "sectorid", "sectorId")):
                continue
            field, dimension, metric = "demandGwh", "energy", "sales"
            raw_value = _get(row, metric)
            unit = str(_get(row, f"{metric}-units", f"{metric}_units") or "").strip()
        elif route == "generation":
            if not _is_generation_sector_total(_get(row, "sectorid", "sectorId")):
                continue
            if index not in selected_generation_indexes:
                continue
            metric, dimension = "generation", "energy"
            raw_value = _get(row, metric)
            unit = str(_get(row, f"{metric}-units", f"{metric}_units") or "").strip()
            fuel = str(_get(row, "fueltypeid", "fuelTypeId") or "").strip().upper()
            value = normalize_metric_value(raw_value, unit=unit, dimension=dimension)
            metadata = _source_meta(
                row, facet=facet, route_id=route, payload=payload, series=metric, unit=unit
            )
            if not _is_generation_fuel_total(fuel):
                technology = _FUEL_TECHNOLOGY.get(fuel, "other")
                if fuel not in _FUEL_TECHNOLOGY:
                    unknown_fuel_codes.add(fuel)
                mix_field = f"generationMixGwh.{technology}"
                fuel_key = (geography_id, year, fuel)
                if fuel_key in generation_mix_keys:
                    raise ValueError(f"duplicate EIA generation fuel row: {fuel_key}")
                generation_mix_keys.add(fuel_key)
                if value is not None and value < 0 and fuel not in _NET_STORAGE_FUEL_CODES:
                    raise ValueError(f"EIA generation mix cannot be negative for fuel {fuel}")
                if value is not None:
                    record["generationMixGwh"][technology] = (
                        record["generationMixGwh"].get(technology, 0.0) + value
                    )
                existing_meta = record["sourceSeries"].get(mix_field)
                if existing_meta is None:
                    record["sourceSeries"][mix_field] = metadata
                elif "aggregatedFacets" in existing_meta:
                    existing_meta["aggregatedFacets"].append(metadata)
                else:
                    record["sourceSeries"][mix_field] = {
                        "aggregatedFacets": [existing_meta, metadata]
                    }
                record["unitMetadata"][mix_field] = {
                    "sourceUnit": unit,
                    "canonicalUnit": "GWh",
                }
                continue
            field = "localGenerationGwh"
        elif route == "capability":
            metric, dimension, field = "capability", "power", "dependableCapacityMw"
            raw_value = _get(row, metric)
            unit = str(_get(row, f"{metric}-units", f"{metric}_units") or "").strip()
            producer = str(_get(row, "producerTypeId", "producertypeid") or "").strip().upper()
            fuel = str(_get(row, "fuelTypeId", "fueltypeid") or "").strip().upper()
            key = (geography_id, year)
            is_total = _is_capability_producer_total(
                producer
            ) and _is_capability_fuel_total(fuel)
            if key in capability_totals and not is_total:
                continue
            if not is_total:
                if not producer or not fuel:
                    continue
                if _is_capability_producer_total(producer) or _is_capability_fuel_total(fuel):
                    # Partial subtotals overlap leaf cells and cannot be safely summed.
                    continue
                leaf_key = (geography_id, year, producer, fuel)
                if leaf_key in capability_leaf_keys:
                    raise ValueError(f"duplicate EIA capability component: {leaf_key}")
                capability_leaf_keys.add(leaf_key)
                value = normalize_metric_value(raw_value, unit=unit, dimension=dimension)
                if value is not None and value < 0:
                    raise ValueError("EIA capability cannot be negative")
                if value is not None:
                    record[field] = (record[field] or 0.0) + value
                component = _source_meta(
                    row, facet=facet, route_id=route, payload=payload, series=metric, unit=unit
                )
                record["sourceSeries"].setdefault(field, {"aggregatedFacets": []})[
                    "aggregatedFacets"
                ].append(component)
                record["unitMetadata"][field] = {
                    "sourceUnit": unit,
                    "canonicalUnit": "MW",
                }
                continue
        elif route == "interchange":
            metric, dimension, field = "value", "energy", "netInterchangeGwh"
            raw_value = _get(row, metric)
            unit = str(_get(row, "value-units", "value_units", "unit") or "").strip()
        else:
            series = synthetic_series
            if series not in _SYNTHETIC_SERIES:
                raise ValueError(f"unsupported EIA series: {series or '<missing>'}")
            field, dimension = _SYNTHETIC_SERIES[series]
            metric = series
            raw_value = _get(row, "value")
            unit = str(_get(row, "unit", "units") or "").strip()
            fuel = str(_get(row, "fueltypeid", "fuelTypeId") or "").strip().upper()
            if field == "localGenerationGwh" and not _is_all(fuel):
                technology = _FUEL_TECHNOLOGY.get(fuel, "other")
                value = normalize_metric_value(raw_value, unit=unit, dimension=dimension)
                if value is not None and value < 0 and fuel not in _NET_STORAGE_FUEL_CODES:
                    raise ValueError(f"EIA generation mix cannot be negative for fuel {fuel}")
                fuel_key = (geography_id, year, fuel)
                if fuel_key in generation_mix_keys:
                    raise ValueError(f"duplicate EIA generation fuel row: {fuel_key}")
                generation_mix_keys.add(fuel_key)
                if value is not None:
                    record["generationMixGwh"][technology] = (
                        record["generationMixGwh"].get(technology, 0.0) + value
                    )
                mix_field = f"generationMixGwh.{technology}"
                record["sourceSeries"][mix_field] = _source_meta(
                    row,
                    facet=facet,
                    route_id=route,
                    payload=payload,
                    series=series,
                    unit=unit,
                )
                record["unitMetadata"][mix_field] = {
                    "sourceUnit": unit,
                    "canonicalUnit": "GWh",
                }
                continue

        value = normalize_metric_value(raw_value, unit=unit, dimension=dimension)
        metadata = _source_meta(
            row, facet=facet, route_id=route, payload=payload, series=metric, unit=unit
        )
        _set_field(
            record,
            field=field,
            value=value,
            unit=unit,
            dimension=dimension,
            metadata=metadata,
        )

    records = [grouped[key] for key in sorted(grouped) if grouped[key]["sourceSeries"]]
    for record in records:
        total = record.get("localGenerationGwh")
        if total is None:
            continue
        mix_total = sum(record["generationMixGwh"].values())
        tolerance = max(1e-6, abs(float(total)) * 1e-6)
        if mix_total > float(total) + tolerance:
            raise ValueError(
                f"EIA generation mix {mix_total} GWh exceeds all-fuel total "
                f"{total} GWh for {record['geographyId']} {record['year']}"
            )
    for record in records:
        for metadata in record["sourceSeries"].values():
            facets = metadata.get("aggregatedFacets")
            if facets:
                facets.sort(
                    key=lambda item: (
                        str(item.get("rawFuelCode") or ""),
                        json.dumps(item, sort_keys=True, default=str),
                    )
                )
        series_key = ",".join(sorted(record["sourceSeries"]))
        record["sourceRecordId"] = (
            f"{EIA_SOURCE_ID}:{route}:{record['geographyId']}:{record['year']}:{series_key}"
        )
        record["unmappedBalancingAuthorities"] = sorted(unmapped_authorities)
        record["sourceResponseMetadata"] = {
            "routeId": route,
            "apiVersion": payload.get("apiVersion"),
            "frequency": response.get("frequency"),
            "dateFormat": response.get("dateFormat"),
            "requestCommand": (payload.get("request") or {}).get("command"),
        }
    if report is not None:
        report["unmappedBalancingAuthorities"] = sorted(unmapped_authorities)
        report["unknownFuelCodes"] = sorted(unknown_fuel_codes)
    return records


class EiaV2Connector:
    source_id = EIA_SOURCE_ID

    def __init__(
        self,
        base_url: str | None = EIA_API_V2_URL,
        api_key: str | None = EIA_API_KEY,
    ) -> None:
        if base_url:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("EIA API v2 URL must be publicly addressable")
        self.base_url = base_url.rstrip("/") + "/" if base_url else None
        self.api_key = api_key.strip() if api_key else None

    def fetch(
        self,
        *,
        params: Mapping[str, Any],
        path: str | None = None,
        route_id: str | None = None,
        page_size: int = 5000,
        now: datetime | None = None,
        client: httpx.Client | None = None,
    ) -> ConnectorResult:
        checked_at = now or datetime.now(UTC)
        if route_id is not None and route_id not in EIA_ROUTE_PATHS:
            raise ValueError(f"unsupported EIA route ID: {route_id}")
        selected_path = path or (EIA_ROUTE_PATHS.get(route_id or "") if route_id else None)
        if not selected_path:
            raise ValueError("EIA fetch requires a route_id or path")
        selected_route = route_id
        if selected_route is None:
            normalized_path = selected_path.strip("/")
            selected_route = next(
                (
                    candidate
                    for candidate, candidate_path in EIA_ROUTE_PATHS.items()
                    if candidate_path.strip("/") == normalized_path
                ),
                None,
            )
        if page_size <= 0:
            raise ValueError("EIA page size must be positive")
        if selected_route == "interchange":
            raise ValueError(
                "EIA connector never fetches direct RTO interchange; normalize only "
                "an externally aggregated annual artifact"
            )
        if not self.base_url:
            return ConnectorResult(
                source_id=self.source_id,
                state=ConnectorState.NOT_CONFIGURED,
                payload=None,
                message="configure a public EIA API v2 endpoint to enable state observations",
            )
        if selected_route in _EIA_ROUTE_QUERIES:
            _validate_eia_route_query(selected_route, params)

        base_query = dict(params)
        if self.api_key:
            base_query["api_key"] = self.api_key
        start_offset = int(base_query.pop("offset", 0))
        base_query["length"] = page_size
        owns_client = client is None
        session = client or httpx.Client()
        combined: dict[str, Any] | None = None
        collected: list[dict[str, Any]] = []
        offset = start_offset
        try:
            while True:
                query = {**base_query, "offset": offset}
                response = session.get(
                    urljoin(self.base_url, selected_path.lstrip("/")), params=query
                )
                response.raise_for_status()
                payload = response.json()
                response_meta, page_rows = _response(payload)
                if combined is None:
                    combined = dict(payload)
                    combined["response"] = dict(response_meta)
                tagged_rows = []
                for raw_row in page_rows:
                    row = dict(raw_row)
                    if selected_route:
                        row["_routeId"] = selected_route
                        row["_series"] = selected_route
                    tagged_rows.append(row)
                collected.extend(tagged_rows)
                try:
                    total = int(response_meta.get("total", len(collected)))
                except (TypeError, ValueError) as error:
                    raise ValueError("EIA response total must be an integer") from error
                if not page_rows or start_offset + len(collected) >= total:
                    break
                offset += len(page_rows)
            assert combined is not None
            combined["response"]["data"] = collected
            combined["response"]["total"] = str(total)
            body = json.dumps(
                _scrub_secrets(combined, secrets=(self.api_key or "",)),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as error:
            message = str(error)
            if self.api_key:
                message = _redact_text(message, (self.api_key,))
            return ConnectorResult(
                source_id=self.source_id,
                state=ConnectorState.FAILED,
                payload=None,
                message=message,
            )
        finally:
            if owns_client:
                session.close()
        return ConnectorResult(
            source_id=self.source_id,
            state=ConnectorState.CURRENT,
            payload=FetchPayload(
                source_id=self.source_id,
                retrieved_at=checked_at,
                media_type="application/json",
                body=body,
            ),
        )
