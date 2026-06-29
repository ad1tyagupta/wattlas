from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from grid_scope.connectors.licensing import (
    normalize_licence,
    require_redistributable_licence,
)
from grid_scope.connectors.regional_electricity import normalize_metric_value


EMBER_SOURCE_ID = "ember-yearly-electricity-data"
EMBER_SOURCE_URL = "https://ember-energy.org/data/yearly-electricity-data/"
EMBER_LICENCE = "CC-BY-4.0"

_TECHNOLOGY_ALIASES = {
    "bioenergy": "biomass",
    "biomass": "biomass",
    "coal": "coal",
    "gas": "gas",
    "geothermal": "geothermal",
    "hydro": "hydro",
    "nuclear": "nuclear",
    "oil": "oil",
    "other fossil": "other",
    "other renewables": "other",
    "solar": "solar",
    "wind": "wind",
}


def normalize_ember_rows(
    rows: list[dict[str, str]], *, country_lookup: dict[str, str] | None = None
) -> list[dict]:
    lookup = country_lookup or {}
    normalized: list[dict] = []
    for row in rows:
        iso3 = (row.get("Country code") or "").strip() or lookup.get(
            (row.get("Country") or "").strip()
        )
        if not iso3:
            continue
        raw_value = (row.get("Value") or "").strip()
        normalized.append(
            {
                "countryIso3": iso3,
                "value": float(raw_value) if raw_value else None,
            }
        )
    return normalized


def _first(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _technology(value: str) -> str | None:
    key = value.strip().lower()
    return _TECHNOLOGY_ALIASES.get(key)


def _normalized_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("requires a public source URL")
    path = parsed.path.rstrip("/")
    return parsed._replace(
        scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), path=path,
        params="", fragment="",
    ).geturl()


def _metric_kind(row: dict[str, Any]) -> tuple[str, str | None] | None:
    """Classify only country-control energy rows from Ember's full dataset."""

    category = _first(row, "Category", "category").lower()
    variable = _first(row, "Variable", "Metric", "metric").lower()
    subcategory = _first(row, "Subcategory", "subcategory").lower()
    unit = _first(row, "Unit", "unit")
    # Use the unit converter only as a vocabulary check, never on the row value.
    try:
        normalize_metric_value(None, unit=unit, dimension="energy")
    except ValueError:
        return None
    if category in {"electricity demand", "demand"} and variable in {
        "demand", "total demand", "electricity demand", "electricity consumption",
    }:
        return ("demand", None)
    if category in {"electricity generation", "generation"} and variable in {
        "total generation", "electricity generation", "generation", "net generation",
    }:
        return ("generation", None)
    if category in {"electricity generation", "generation"}:
        technology = _technology(variable)
        if technology is not None and (not subcategory or subcategory == "fuel"):
            return ("fuel", technology)
    return None


def normalize_ember_yearly_rows(
    rows: list[dict[str, Any]],
    *,
    country_lookup: dict[str, str] | None = None,
    report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize Ember Yearly Electricity Data into country control records.

    Country controls deliberately use ``geographyLevel=country`` so they cannot
    enter the ADM1 official-observation path accidentally. Missing values are
    retained as ``None`` and are never coerced to zero.
    """

    lookup = country_lookup or {}
    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        metric_kind = _metric_kind(row)
        if metric_kind is None:
            if report is not None:
                report["ignoredRows"] = int(report.get("ignoredRows", 0)) + 1
            continue
        country_name = _first(row, "Area", "Country")
        iso3 = _first(row, "ISO 3 code", "Country code", "country_iso3").upper()
        iso3 = iso3 or lookup.get(country_name, "").upper()
        if not iso3:
            raise ValueError(f"Ember row {index} lacks a country ISO3 mapping")
        if re.fullmatch(r"[A-Z]{3}", iso3) is None:
            raise ValueError(f"Ember row {index} has invalid country ISO3 code: {iso3}")
        year_text = _first(row, "Year", "year")
        if not year_text:
            raise ValueError(f"Ember row {index} lacks a year")
        try:
            year = int(year_text)
        except ValueError as error:
            raise ValueError(f"Ember row {index} has invalid year: {year_text}") from error
        if not 1900 <= year <= 2100:
            raise ValueError(f"Ember row {index} has invalid year: {year}")

        unit = _first(row, "Unit", "unit")
        raw_value = row.get("Value", row.get("value"))
        value = normalize_metric_value(raw_value, unit=unit, dimension="energy")
        source_url = _first(row, "Source URL", "source_url") or EMBER_SOURCE_URL
        licence = _first(row, "Licence", "License", "licence") or EMBER_LICENCE
        updated_at = _first(row, "Last Updated", "Updated At", "updated_at") or None
        try:
            normalized_url = _normalized_url(source_url)
        except ValueError as error:
            raise ValueError(f"Ember row {index} requires a public source URL") from error
        require_redistributable_licence(licence, label=f"Ember row {index}")
        normalized_updated_at: str | None = None
        if updated_at:
            try:
                normalized_updated_at = date.fromisoformat(str(updated_at)[:10]).isoformat()
            except ValueError as error:
                raise ValueError(f"Ember row {index} has invalid update date") from error
        record = grouped.setdefault(
            (iso3, year),
            {
                "geographyId": iso3,
                "geographyLevel": "country",
                "countryIso3": iso3,
                "year": year,
                "period": "annual",
                "demandGwh": None,
                "localGenerationGwh": None,
                "generationMixGwh": {},
                "sourceIds": [EMBER_SOURCE_ID],
                "sourceId": EMBER_SOURCE_ID,
                "sourceRecordId": f"{EMBER_SOURCE_ID}:{iso3}:{year}",
                "sourceType": "research_verified",
                "sourceUrl": source_url,
                "licence": licence,
                "updatedAt": normalized_updated_at,
                "observationDate": f"{year}-12-31",
                "valueKind": "reported",
                "methodId": "ember-yearly-v1",
                "unitMetadata": {},
                "_lineage": (normalized_url, normalize_licence(licence), normalized_updated_at),
                "_seenMetrics": set(),
            },
        )
        lineage = (normalized_url, normalize_licence(licence), normalized_updated_at)
        if record["_lineage"] != lineage:
            raise ValueError(f"conflicting Ember lineage for {iso3} {year}")
        if normalized_updated_at:
            updated_date = date.fromisoformat(normalized_updated_at)
            record["freshnessDays"] = (updated_date - date(year, 12, 31)).days
        else:
            record["freshnessDays"] = None
        kind, technology = metric_kind
        if kind == "demand":
            field = "demandGwh"
            if field in record["_seenMetrics"]:
                raise ValueError(f"duplicate Ember {field} for {iso3} {year}")
            record["_seenMetrics"].add(field)
            record[field] = value
            record["unitMetadata"][field] = {"sourceUnit": unit, "canonicalUnit": "GWh"}
        elif kind == "generation":
            field = "localGenerationGwh"
            if field in record["_seenMetrics"]:
                raise ValueError(f"duplicate Ember {field} for {iso3} {year}")
            record["_seenMetrics"].add(field)
            record[field] = value
            record["unitMetadata"][field] = {"sourceUnit": unit, "canonicalUnit": "GWh"}
        else:
            assert kind == "fuel" and technology is not None
            if technology in record["generationMixGwh"]:
                raise ValueError(f"duplicate Ember {technology} generation for {iso3} {year}")
            if value is not None:
                record["generationMixGwh"][technology] = value
            record["unitMetadata"][f"generationMixGwh.{technology}"] = {
                "sourceUnit": unit,
                "canonicalUnit": "GWh",
            }
    output: list[dict[str, Any]] = []
    for key in sorted(grouped):
        record = grouped[key]
        record.pop("_lineage")
        record.pop("_seenMetrics")
        output.append(record)
    return output


def normalize_ember_yearly_csv(
    path: Path | str,
    *,
    country_lookup: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        return normalize_ember_yearly_rows(list(csv.DictReader(source)), country_lookup=country_lookup)
