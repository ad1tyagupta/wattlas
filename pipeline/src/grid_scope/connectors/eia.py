from __future__ import annotations

from datetime import UTC, date, datetime
import json
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse

import httpx

from grid_scope.config import EIA_API_KEY, EIA_API_V2_URL
from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.connectors.regional_electricity import normalize_metric_value, validate_region_mapping
from grid_scope.models import ConnectorState


EIA_SOURCE_ID = "eia-api-v2"
EIA_SOURCE_URL = "https://www.eia.gov/opendata/"
EIA_LICENCE = "US-PUBLIC-DOMAIN"

_FUEL_ALIASES = {
    "BIT": "coal",
    "COL": "coal",
    "DFO": "oil",
    "GEO": "geothermal",
    "HYC": "hydro",
    "NG": "gas",
    "NUC": "nuclear",
    "OBG": "biomass",
    "PET": "oil",
    "SUN": "solar",
    "WND": "wind",
}

_SERIES_ALIASES = {
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


def _rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("response")
    if not isinstance(response, Mapping) or not isinstance(response.get("data"), list):
        raise ValueError("unexpected EIA API v2 response: response.data is required")
    frequency = str(response.get("frequency") or "annual")
    if frequency not in {"annual", "yearly"}:
        raise ValueError(f"EIA regional electricity requires annual data, got {frequency}")
    rows = response["data"]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("unexpected EIA API v2 response row")
    return rows


def _series(row: Mapping[str, Any]) -> str:
    value = row.get("series") or row.get("seriesId") or row.get("series_id")
    return str(value or "").strip().lower().replace("_", "-")


def _period(row: Mapping[str, Any]) -> int:
    raw = str(row.get("period") or row.get("year") or "").strip()
    try:
        year = int(raw[:4])
    except ValueError as error:
        raise ValueError(f"invalid EIA period: {raw}") from error
    if len(raw) < 4 or not 1900 <= year <= 2100:
        raise ValueError(f"invalid EIA period: {raw}")
    return year


def _source_meta(row: Mapping[str, Any], *, facet: str) -> dict[str, Any]:
    return {
        "series": _series(row),
        "seriesDescription": row.get("series-description") or row.get("seriesDescription"),
        "facet": facet,
        "sourceUnit": row.get("unit") or row.get("units"),
    }


def _country_iso3(geography_id: str) -> str:
    # This connector currently normalizes United States EIA APIs only. Keeping
    # this explicit avoids inferring ISO3 from Wattlas's ISO2-prefixed ADM1 IDs.
    if not geography_id.startswith("US-"):
        raise ValueError(f"EIA state mapping must target a US ADM1 geography: {geography_id}")
    return "USA"


def normalize_eia_state(
    payload: Mapping[str, Any],
    *,
    state_mapping: Mapping[str, str],
    active_geography_ids: Iterable[str],
    balancing_authority_mapping: Mapping[str, str] | None = None,
    source_url: str = EIA_SOURCE_URL,
    retrieved_at: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize EIA v2 state series, using BA interchange only if explicitly mapped."""

    rows = _rows(payload)
    observed_state_codes = {
        str(row.get("stateid") or row.get("stateId") or "").strip()
        for row in rows
        if row.get("stateid") or row.get("stateId")
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
    unmapped_authorities: set[str] = set()
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
    for index, row in enumerate(rows, start=1):
        series = _series(row)
        if series not in _SERIES_ALIASES:
            raise ValueError(f"unsupported EIA series: {series or '<missing>'}")
        field, dimension = _SERIES_ALIASES[series]
        state_code = str(row.get("stateid") or row.get("stateId") or "").strip()
        authority_code = str(
            row.get("balancingAuthority") or row.get("balancing-authority") or row.get("ba") or ""
        ).strip()
        if state_code:
            geography_id = states[state_code]
            facet = state_code
        elif series == "net-interchange" and authority_code:
            # A balancing authority may span several states. Never infer a state;
            # ignore it unless a curated one-to-one mapping was explicitly supplied.
            if authority_code not in authorities:
                unmapped_authorities.add(authority_code)
                continue
            geography_id = authorities[authority_code]
            facet = authority_code
        else:
            raise ValueError(f"EIA row {index} lacks a mapped state facet")
        year = _period(row)
        value = normalize_metric_value(
            row.get("value"),
            unit=str(row.get("unit") or row.get("units") or ""),
            dimension=dimension,
        )
        if value is not None and field != "netInterchangeGwh" and value < 0:
            raise ValueError(f"EIA {field} cannot be negative")
        record = grouped.setdefault(
            (geography_id, year),
            {
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
                "generationMixGwh": {},
                "sourceSeries": {},
                "sourceIds": [EIA_SOURCE_ID],
                "sourceId": EIA_SOURCE_ID,
                "sourceRecordId": f"{EIA_SOURCE_ID}:{geography_id}:{year}",
                "sourceType": "official_verified",
                "sourceUrl": source_url,
                "licence": EIA_LICENCE,
                "updatedAt": retrieved_at,
                "observationDate": f"{year}-12-31",
                "freshnessDays": (
                    (retrieved_date - date(year, 12, 31)).days if retrieved_date else None
                ),
                "valueKind": "reported",
                "methodId": "eia-api-v2-state-annual-v1",
                "unitMetadata": {},
            },
        )
        fuel = str(row.get("fueltypeid") or row.get("fuelTypeId") or "").strip().upper()
        is_mix = field == "localGenerationGwh" and fuel not in {"", "ALL", "TOTAL", "TSN"}
        if is_mix:
            technology = _FUEL_ALIASES.get(fuel, "other")
            if technology in record["generationMixGwh"]:
                raise ValueError(f"duplicate EIA generation mix value for {geography_id} {year} {technology}")
            if value is not None:
                record["generationMixGwh"][technology] = value
            metadata_field = f"generationMixGwh.{technology}"
        else:
            if record[field] is not None:
                raise ValueError(f"duplicate EIA value for {geography_id} {year} {field}")
            record[field] = value
            metadata_field = field
        record["sourceSeries"][metadata_field] = _source_meta(row, facet=facet)
        record["unitMetadata"][metadata_field] = {
            "sourceUnit": str(row.get("unit") or row.get("units") or ""),
            "canonicalUnit": "MW" if dimension == "power" else "GWh",
        }

    records = [grouped[key] for key in sorted(grouped)]
    for record in records:
        series_key = ",".join(sorted(record["sourceSeries"]))
        record["sourceRecordId"] = (
            f"{EIA_SOURCE_ID}:{record['geographyId']}:{record['year']}:{series_key}"
        )
        record["unmappedBalancingAuthorities"] = sorted(unmapped_authorities)
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
        path: str,
        params: Mapping[str, Any],
        now: datetime | None = None,
        client: httpx.Client | None = None,
    ) -> ConnectorResult:
        checked_at = now or datetime.now(UTC)
        if not self.base_url:
            return ConnectorResult(
                source_id=self.source_id,
                state=ConnectorState.NOT_CONFIGURED,
                payload=None,
                message="configure a public EIA API v2 endpoint to enable state observations",
            )
        query = dict(params)
        if self.api_key:
            query["api_key"] = self.api_key
        owns_client = client is None
        session = client or httpx.Client()
        try:
            response = session.get(urljoin(self.base_url, path.lstrip("/")), params=query)
            response.raise_for_status()
            payload = response.json()
            _rows(payload)
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as error:
            message = str(error)
            if self.api_key:
                message = message.replace(self.api_key, "[redacted]")
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
