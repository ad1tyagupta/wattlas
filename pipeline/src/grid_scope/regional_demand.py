from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from grid_scope.connectors.licensing import require_redistributable_licence


SCHEMA_VERSION = "wattlas-regional-demand-weights-v1"
ALLOCATION_METHOD_ID = "adm1-demand-allocation-v1"
FORECAST_INCREMENT_METHOD_ID = "forward-infrastructure-demand-increments-v1"
DEFAULT_COMPONENT_WEIGHTS = {
    "activity": 0.55,
    "population": 0.30,
    "industrial": 0.15,
}
TARGET_YEARS = tuple(range(2026, 2032))
_SHARE_FIELDS = {
    "activity": "activityShare",
    "population": "populationShare",
    "industrial": "industrialShare",
}
_DEFAULT_UNCERTAINTY = {
    "multi_covariate": {
        "baseFraction": 0.12,
        "ageFractionPerYear": 0.01,
        "maximumFraction": 0.30,
        "baseConfidence": 82.0,
        "confidencePointsLostPerYear": 1.5,
    },
    "population_only": {
        "baseFraction": 0.25,
        "ageFractionPerYear": 0.02,
        "maximumFraction": 0.50,
        "baseConfidence": 68.0,
        "confidencePointsLostPerYear": 2.5,
    },
}


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _fingerprint(value: object) -> str:
    return f"sha256:{sha256(_stable_json(value).encode()).hexdigest()}"


def _finite_nonnegative(value: object, *, label: str, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite nonnegative number")
    if isinstance(value, str):
        value = value.strip()
        if not value and allow_none:
            return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a finite nonnegative number") from error
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be a finite nonnegative number")
    return result


def _quality(value: object, *, label: str, default: float) -> float:
    if value is None:
        return default
    result = _finite_nonnegative(value, label=label)
    assert result is not None
    if result > 100:
        raise ValueError(f"{label} must be within 0-100")
    return result


def _share(value: object, *, label: str, allow_none: bool = False) -> float | None:
    result = _finite_nonnegative(value, label=label, allow_none=allow_none)
    if result is not None and result > 1:
        raise ValueError(f"{label} must be within 0-1")
    return result


def _range(value: object, *, label: str) -> dict[str, float]:
    if isinstance(value, Mapping):
        missing = {"low", "central", "high"} - set(value)
        if missing:
            raise ValueError(f"{label} range requires low, central, and high")
        low = _finite_nonnegative(value["low"], label=f"{label} low")
        central = _finite_nonnegative(value["central"], label=f"{label} central")
        high = _finite_nonnegative(value["high"], label=f"{label} high")
    else:
        central = _finite_nonnegative(value, label=label)
        low = high = central
    assert low is not None and central is not None and high is not None
    if not low <= central <= high:
        raise ValueError(f"{label} range must be ordered low <= central <= high")
    return {"low": low, "central": central, "high": high}


def _id_list(value: object, *, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of unique non-empty strings")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label} must contain only non-empty strings")
        normalized = item.strip()
        if normalized in seen:
            raise ValueError(f"duplicate {label}: {normalized}")
        seen.add(normalized)
        result.append(normalized)
    if not result and not allow_empty:
        raise ValueError(f"{label} requires at least one value")
    return sorted(result)


def _source_ids(value: object, *, label: str) -> list[str]:
    return _id_list(value, label=f"{label} source IDs")


def _country_control(control: Mapping[str, Any]) -> dict[str, Any]:
    demand = control.get("demandGwh")
    if demand is None:
        raise ValueError("country control demand is unavailable")
    demand_range = _range(demand, label="country control demand")
    country = str(control.get("countryIso3") or "").strip().upper()
    if re.fullmatch(r"[A-Z]{3}", country) is None:
        raise ValueError("country control requires an ISO3 country")
    try:
        year = int(control.get("year"))
    except (TypeError, ValueError) as error:
        raise ValueError("country control requires a year") from error
    return {
        **dict(control),
        "demandGwh": demand_range,
        "countryIso3": country,
        "year": year,
        "sourceIds": _source_ids(control.get("sourceIds"), label="country control"),
        "confidence": _quality(control.get("confidence"), label="country control confidence", default=80),
        "coverage": _quality(control.get("coverage"), label="country control coverage", default=100),
    }


def _normalized_regions(regions: Iterable[Mapping[str, Any]], country: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in regions:
        geography_id = str(raw.get("geographyId") or raw.get("id") or "").strip()
        if not geography_id:
            raise ValueError("regional demand weights require a geography ID")
        if geography_id in seen:
            raise ValueError(f"duplicate geography ID: {geography_id}")
        seen.add(geography_id)
        region_country = str(raw.get("countryIso3") or country).strip().upper()
        if region_country != country:
            raise ValueError(f"regional demand country mismatch for {geography_id}")
        normalized = dict(raw)
        normalized["geographyId"] = geography_id
        normalized["countryIso3"] = country
        for component, field in _SHARE_FIELDS.items():
            normalized[field] = _share(
                raw.get(field), label=f"{component} share for {geography_id}", allow_none=True
            )
        normalized["sourceIds"] = _source_ids(
            raw.get("sourceIds") or ["regional-weight-unspecified"],
            label=f"weights for {geography_id}",
        )
        normalized["coverage"] = _quality(raw.get("coverage"), label=f"coverage for {geography_id}", default=100)
        result.append(normalized)
    if not result:
        raise ValueError("country allocation requires at least one ADM1 region")
    result.sort(key=lambda row: row["geographyId"])
    for component, field in _SHARE_FIELDS.items():
        values = [row[field] for row in result]
        if all(value is not None for value in values):
            total = math.fsum(float(value) for value in values)
            if not math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"{component} shares must sum to 1; got {total}")
    return result


def _official_observations(
    observations: Iterable[Mapping[str, Any]],
    *,
    country: str,
    year: int,
    active_ids: set[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in observations:
        geography_id = str(raw.get("geographyId") or "").strip()
        if geography_id in result:
            raise ValueError(f"duplicate official observation for {geography_id}")
        if geography_id not in active_ids:
            raise ValueError(f"official observation uses unknown geography ID: {geography_id}")
        if str(raw.get("countryIso3") or "").strip().upper() != country:
            raise ValueError(f"official observation country mismatch for {geography_id}")
        if int(raw.get("year")) != year:
            raise ValueError(f"official observation year mismatch for {geography_id}")
        value_kind = str(raw.get("valueKind") or "").strip()
        if value_kind not in {"observed", "reported"}:
            raise ValueError("official observations must be observed or reported")
        result[geography_id] = {
            **dict(raw),
            "demandGwh": _range(raw.get("demandGwh"), label=f"official demand for {geography_id}"),
            "sourceIds": _source_ids(raw.get("sourceIds"), label=f"official observation {geography_id}"),
            "confidence": _quality(raw.get("confidence"), label=f"official confidence for {geography_id}", default=95),
            "coverage": _quality(raw.get("coverage"), label=f"official coverage for {geography_id}", default=100),
        }
    return result


def _effective_covariates(region: Mapping[str, Any]) -> tuple[str, dict[str, float], float, dict[str, dict[str, Any]]]:
    available = {
        component: float(region[field])
        for component, field in _SHARE_FIELDS.items()
        if region.get(field) is not None
    }
    if "population" not in available:
        raise ValueError(f"population is unavailable for {region['geographyId']}")
    denominator = math.fsum(DEFAULT_COMPONENT_WEIGHTS[key] for key in available)
    effective = {
        key: DEFAULT_COMPONENT_WEIGHTS[key] / denominator for key in sorted(available)
    }
    grade = "population_only" if set(available) == {"population"} else "multi_covariate"
    disclosed = {
        component: {
            "available": component in available,
            "share": available.get(component),
            "sourceIds": list(region.get("sourceIds") or []),
        }
        for component in DEFAULT_COMPONENT_WEIGHTS
    }
    return grade, effective, denominator, disclosed


def load_regional_demand_methods(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != "wattlas-regional-demand-methods-v1":
        raise ValueError("unsupported regional demand methods schema")
    if payload.get("publicDataOnly") is not True:
        raise ValueError("regional demand methods must require public data")
    methods = payload.get("methods")
    if not isinstance(methods, Mapping):
        raise ValueError("regional demand methods require method definitions")
    missing_grades = {"official", "multi_covariate", "population_only"} - set(methods)
    if missing_grades:
        raise ValueError(
            "regional demand methods lack required grades: "
            + ", ".join(sorted(missing_grades))
        )
    official = methods["official"]
    if not isinstance(official, Mapping):
        raise ValueError("regional demand official method must be an object")
    official_kinds = official.get("valueKind")
    if (
        not str(official.get("methodId") or "").strip()
        or not isinstance(official_kinds, list)
        or not {"observed", "reported"}.issubset(set(official_kinds))
        or not str(official.get("uncertainty") or "").strip()
    ):
        raise ValueError("regional demand official method lacks provenance or value-kind rules")
    for grade in ("multi_covariate", "population_only"):
        settings = methods.get(grade)
        if not isinstance(settings, Mapping):
            raise ValueError(f"regional demand methods lack {grade}")
        for field in (
            "baseUncertaintyFraction", "ageFractionPerYear",
            "maximumUncertaintyFraction", "baseConfidence",
            "confidencePointsLostPerYear",
        ):
            _finite_nonnegative(settings.get(field), label=f"{grade} {field}")
        if float(settings["maximumUncertaintyFraction"]) > 1:
            raise ValueError(f"{grade} maximum uncertainty must be within 0-1")
        if float(settings["baseConfidence"]) > 100:
            raise ValueError(f"{grade} confidence must be within 0-100")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("regional demand methods require public source provenance")
    source_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping):
            raise ValueError("regional demand method source must be an object")
        source_id = str(source.get("id") or "").strip()
        if not source_id or source_id in source_ids:
            raise ValueError("regional demand method sources require unique source IDs")
        source_ids.add(source_id)
        source_url = str(source.get("url") or "").strip()
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"regional demand source {source_id} requires a public source URL")
        require_redistributable_licence(
            str(source.get("licence") or ""), label=f"regional demand source {source_id}"
        )
    return payload


def _uncertainty(
    grade: str,
    *,
    as_of_year: int,
    covariate_year: int,
    method_config: Mapping[str, Any] | None,
) -> tuple[float, float]:
    if method_config is None:
        settings = _DEFAULT_UNCERTAINTY[grade]
    else:
        raw = method_config.get("methods", {}).get(grade, {})
        settings = {
            "baseFraction": float(raw["baseUncertaintyFraction"]),
            "ageFractionPerYear": float(raw["ageFractionPerYear"]),
            "maximumFraction": float(raw["maximumUncertaintyFraction"]),
            "baseConfidence": float(raw["baseConfidence"]),
            "confidencePointsLostPerYear": float(raw["confidencePointsLostPerYear"]),
        }
    age = max(0, as_of_year - covariate_year)
    fraction = min(
        settings["maximumFraction"],
        settings["baseFraction"] + age * settings["ageFractionPerYear"],
    )
    confidence = max(0.0, settings["baseConfidence"] - age * settings["confidencePointsLostPerYear"])
    return fraction, confidence


def allocate_country_demand(
    *,
    regions: Iterable[Mapping[str, Any]],
    country_control: Mapping[str, Any] | None = None,
    country_gwh: float | None = None,
    country_iso3: str = "ZZZ",
    year: int = 2024,
    source_ids: list[str] | None = None,
    official_observations: Iterable[Mapping[str, Any]] = (),
    as_of_year: int | None = None,
    covariate_year: int | None = None,
    method_config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Allocate one historical country demand control without adding asset demand.

    ``country_gwh`` is a compatibility convenience for small callers. Production
    callers should pass ``country_control`` so public lineage is explicit.
    """

    if country_control is None:
        if country_gwh is None:
            raise ValueError("country control is unavailable")
        country_control = {
            "demandGwh": country_gwh,
            "countryIso3": country_iso3,
            "year": year,
            "sourceIds": source_ids if source_ids is not None else ["country-control-unspecified"],
            "valueKind": "reported",
            "methodId": "country-control-unspecified",
            "confidence": 50,
            "coverage": 100,
        }
    control = _country_control(country_control)
    normalized = _normalized_regions(regions, control["countryIso3"])
    official = _official_observations(
        official_observations,
        country=control["countryIso3"],
        year=control["year"],
        active_ids={row["geographyId"] for row in normalized},
    )
    official_central = math.fsum(row["demandGwh"]["central"] for row in official.values())
    country_central = control["demandGwh"]["central"]
    tolerance = max(abs(country_central), 1.0) * 1e-12
    if official_central > country_central + tolerance:
        raise ValueError("official ADM1 demand exceeds country control")
    residual = max(0.0, country_central - official_central)
    modelled = [row for row in normalized if row["geographyId"] not in official]
    if residual > tolerance and not modelled:
        raise ValueError("country control has a nonzero residual without modelled regions")

    as_of = int(as_of_year if as_of_year is not None else control["year"])
    covariate = int(covariate_year if covariate_year is not None else control["year"])
    prepared: list[dict[str, Any]] = []
    scores: list[float] = []
    for region in modelled:
        grade, weights, denominator, disclosed = _effective_covariates(region)
        score = math.fsum(weights[key] * float(region[_SHARE_FIELDS[key]]) for key in weights)
        if not math.isfinite(score) or score < 0:
            raise ValueError(f"invalid model weight for {region['geographyId']}")
        prepared.append({
            "region": region,
            "grade": grade,
            "effectiveWeights": weights,
            "effectiveDenominator": denominator,
            "covariates": disclosed,
        })
        scores.append(score)
    total_score = math.fsum(scores)
    if residual > tolerance and total_score <= 0:
        raise ValueError("modelled regional weights cannot allocate a nonzero country residual")
    central_values = [residual * (score / total_score) if total_score else 0.0 for score in scores]
    if central_values:
        correction = residual - math.fsum(central_values)
        tolerance = max(
            math.ulp(residual) * max(2, len(central_values)),
            abs(residual) * 1e-12,
        )
        if not math.isfinite(correction) or abs(correction) > tolerance:
            raise RuntimeError("ADM1 demand rounding residual exceeds bounded float tolerance")
        if correction:
            positive_indices = [index for index, score in enumerate(scores) if score > 0]
            if not positive_indices:
                raise RuntimeError("ADM1 demand rounding residual has no positive allocation weight")
            correction_index = max(
                positive_indices,
                key=lambda index: (scores[index], -index),
            )
            corrected = central_values[correction_index] + correction
            if not math.isfinite(corrected) or corrected < 0:
                raise RuntimeError("ADM1 demand rounding correction would create an invalid allocation")
            central_values[correction_index] = corrected

    output: list[dict[str, Any]] = []
    for geography_id, observation in official.items():
        demand_range = observation["demandGwh"]
        output.append({
            "geographyId": geography_id,
            "geographyLevel": "admin_1",
            "countryIso3": control["countryIso3"],
            "year": control["year"],
            "demandGwh": demand_range,
            "valueKind": observation["valueKind"],
            "methodGrade": "official",
            "methodId": observation.get("methodId") or "official-direct-v1",
            "sourceIds": observation["sourceIds"],
            "sourceUrl": observation.get("sourceUrl"),
            "confidence": observation["confidence"],
            "coverage": observation["coverage"],
            "effectiveWeights": {},
            "effectiveDenominator": None,
            "covariates": {},
            "countryControlGwh": country_central,
            "countryControlSourceIds": control["sourceIds"],
        })
    for item, central in zip(prepared, central_values, strict=True):
        region = item["region"]
        fraction, confidence = _uncertainty(
            item["grade"], as_of_year=as_of, covariate_year=covariate,
            method_config=method_config,
        )
        coverage = min(control["coverage"], region["coverage"])
        calculated_range = _range({
            "low": max(0.0, central * (1 - fraction)),
            "central": central,
            "high": central * (1 + fraction),
        }, label=f"calculated regional demand for {region['geographyId']}")
        output.append({
            "geographyId": region["geographyId"],
            "geographyLevel": "admin_1",
            "countryIso3": control["countryIso3"],
            "year": control["year"],
            "demandGwh": calculated_range,
            "valueKind": "estimated",
            "methodGrade": item["grade"],
            "methodId": ALLOCATION_METHOD_ID,
            "sourceIds": sorted(set(control["sourceIds"]) | set(region["sourceIds"])),
            "sourceUrl": control.get("sourceUrl"),
            "confidence": min(control["confidence"], confidence),
            "coverage": coverage,
            "effectiveWeights": item["effectiveWeights"],
            "effectiveDenominator": item["effectiveDenominator"],
            "covariates": item["covariates"],
            "countryControlGwh": country_central,
            "countryControlSourceIds": control["sourceIds"],
            "covariateYear": covariate,
            "uncertaintyFraction": fraction,
        })
    output.sort(key=lambda row: row["geographyId"])
    if not math.isclose(
        math.fsum(row["demandGwh"]["central"] for row in output),
        country_central,
        rel_tol=1e-6,
        abs_tol=1e-9,
    ):
        raise RuntimeError("ADM1 demand allocation did not reconcile to country control")
    return output


def add_forward_demand_increments(
    base_forecasts: Iterable[Mapping[str, Any]],
    increments: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Apply sourced forward increments once; historical allocation never calls this."""

    bases = [deepcopy(dict(row)) for row in base_forecasts]
    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    base_ranges: dict[tuple[str, int], dict[str, float]] = {}
    already_applied: set[str] = set()
    for row in bases:
        geography_id = str(row.get("geographyId") or "").strip()
        if not geography_id:
            raise ValueError("base forecast requires a geography ID")
        raw_base_year = row.get("year")
        if isinstance(raw_base_year, bool) or not isinstance(raw_base_year, int):
            raise ValueError("base forecast requires a year within 2026-2031")
        base_year = raw_base_year
        if base_year not in TARGET_YEARS:
            raise ValueError("base forecast year must be within 2026-2031")
        key = (geography_id, base_year)
        if key in by_key:
            raise ValueError(f"duplicate base forecast: {geography_id} {base_year}")
        base_ranges[key] = _range(row.get("demandGwh"), label="base forecast demand")
        _source_ids(row.get("sourceIds"), label="base forecast")
        by_key[key] = row
        prior_increment_ids = _id_list(
            row.get("appliedIncrementIds", []),
            label="base prior increment IDs",
            allow_empty=True,
        )
        for normalized_increment_id in prior_increment_ids:
            if normalized_increment_id in already_applied:
                raise ValueError("base forecasts contain duplicate prior increment lineage")
            already_applied.add(normalized_increment_id)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in increments:
        increment_id = str(raw.get("incrementId") or "").strip()
        if not increment_id:
            raise ValueError("forward increment requires an increment ID")
        if increment_id in seen:
            raise ValueError(f"duplicate increment ID: {increment_id}")
        if increment_id in already_applied:
            raise ValueError(f"increment already applied: {increment_id}")
        seen.add(increment_id)
        geography_id = str(raw.get("geographyId") or "").strip()
        try:
            target_year = int(raw.get("targetYear"))
        except (TypeError, ValueError) as error:
            raise ValueError("forward increment requires a target year") from error
        if target_year not in TARGET_YEARS:
            raise ValueError("forward increment target year must be within 2026-2031")
        if (geography_id, target_year) not in by_key:
            raise ValueError(
                f"forward increment requires an exact base forecast for "
                f"{geography_id} {target_year}"
            )
        normalized.append({
            "incrementId": increment_id,
            "geographyId": geography_id,
            "targetYear": target_year,
            "demandGwh": _range(raw.get("demandGwh"), label=f"increment {increment_id}"),
            "sourceIds": _source_ids(raw.get("sourceIds"), label=f"increment {increment_id}"),
        })
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in normalized:
        grouped.setdefault((row["geographyId"], row["targetYear"]), []).append(row)
    output = [by_key[key] for key in sorted(by_key)]
    for (geography_id, target_year), group in sorted(grouped.items()):
        base = by_key[(geography_id, target_year)]
        base_range = base_ranges[(geography_id, target_year)]
        additions = {
            key: math.fsum(row["demandGwh"][key] for row in group)
            for key in ("low", "central", "high")
        }
        base["demandGwh"] = _range({
            key: base_range[key] + additions[key]
            for key in ("low", "central", "high")
        }, label=f"summed forward demand for {geography_id} {target_year}")
        base["appliedIncrementIds"] = sorted(
            set(base.get("appliedIncrementIds") or [])
            | {row["incrementId"] for row in group}
        )
        base["sourceIds"] = sorted(
            set(base.get("sourceIds") or [])
            | {source_id for row in group for source_id in row["sourceIds"]}
        )
        base["methodId"] = FORECAST_INCREMENT_METHOD_ID
    return output


def _component_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    component: str,
    geography_country: Mapping[str, str],
) -> dict[tuple[str, int], dict[str, Any]]:
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for raw in rows:
        geography_id = str(raw.get("geographyId") or raw.get("geography_id") or "").strip()
        if geography_id not in geography_country:
            raise ValueError(f"{component} record uses unknown active ADM1 ID: {geography_id}")
        try:
            year = int(raw.get("year"))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{component} record requires a year") from error
        key = (geography_id, year)
        if key in result:
            raise ValueError(f"duplicate {component} record: {geography_id} {year}")
        value = raw.get(
            "value",
            raw.get("share", raw.get(f"{component}Share", raw.get(f"{component}_share"))),
        )
        raw_source_id = raw.get("sourceId", raw.get("source_id"))
        if not isinstance(raw_source_id, str) or not raw_source_id.strip():
            raise ValueError(f"{component} record requires a source ID")
        source_id = raw_source_id.strip()
        result[key] = {
            "value": _finite_nonnegative(value, label=f"{component} value for {geography_id}"),
            "sourceId": source_id,
        }
    return result


def _normalize_component(
    values: Mapping[tuple[str, int], Mapping[str, Any]],
    *,
    geography_country: Mapping[str, str],
    label: str,
) -> dict[tuple[str, int], float]:
    grouped: dict[tuple[str, int], list[tuple[str, float]]] = {}
    for (geography_id, year), row in values.items():
        grouped.setdefault((geography_country[geography_id], year), []).append((geography_id, float(row["value"])))
    result: dict[tuple[str, int], float] = {}
    for key, rows in sorted(grouped.items()):
        total = math.fsum(value for _, value in rows)
        if total <= 0:
            raise ValueError(f"{label} values cannot normalize a zero country total for {key}")
        for geography_id, value in rows:
            result[(geography_id, key[1])] = value / total
    return result


def build_regional_demand_weights(
    *,
    population_artifact: Mapping[str, Any],
    active_geography_ids: Iterable[str],
    activity_records: Iterable[Mapping[str, Any]] = (),
    industrial_records: Iterable[Mapping[str, Any]] = (),
    official_observations: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    active = sorted({str(value).strip() for value in active_geography_ids if str(value).strip()})
    population_rows = population_artifact.get("records")
    if not isinstance(population_rows, list):
        raise ValueError("population artifact requires records")
    unavailable_rows = population_artifact.get("unavailable", [])
    if not isinstance(unavailable_rows, list):
        raise ValueError("population artifact unavailable markers must be an array")
    population_ids = {str(row.get("geographyId") or "").strip() for row in population_rows}
    relevant_unavailable_rows = [
        row for row in unavailable_rows
        if str(row.get("geographyId") or "").strip() in set(active)
    ]
    unavailable_ids = {
        str(row.get("geographyId") or "").strip() for row in relevant_unavailable_rows
    }
    if not population_ids.issubset(set(active)) or population_ids | unavailable_ids != set(active):
        raise ValueError("population artifact IDs must exactly match active ADM1 IDs")
    geography_country: dict[str, str] = {}
    for row in [*population_rows, *relevant_unavailable_rows]:
        geography_id = str(row.get("geographyId") or "").strip()
        country = str(row.get("country") or "").strip().upper()
        if not geography_id or re.fullmatch(r"[A-Z]{2}", country) is None:
            raise ValueError(f"population record requires an ISO2 country: {geography_id}")
        previous_country = geography_country.setdefault(geography_id, country)
        if previous_country != country:
            raise ValueError(f"population geography changes country: {geography_id}")
    country_active_ids: dict[str, list[str]] = {}
    for geography_id in active:
        country_active_ids.setdefault(geography_country[geography_id], []).append(geography_id)
    unavailable_by_country: dict[str, set[str]] = {}
    unavailable_years_by_country: dict[str, set[int]] = {}
    for row in relevant_unavailable_rows:
        geography_id = str(row.get("geographyId") or "").strip()
        country = geography_country[geography_id]
        try:
            year = int(row.get("year"))
        except (TypeError, ValueError) as error:
            raise ValueError("population unavailable marker requires a target year") from error
        if year not in TARGET_YEARS:
            raise ValueError("population unavailable marker requires a target year")
        unavailable_by_country.setdefault(country, set()).add(geography_id)
        unavailable_years_by_country.setdefault(country, set()).add(year)
    country_level_only_countries = set(unavailable_by_country)
    release = population_artifact.get("sourceRelease")
    primary_source_id = (
        str(release.get("sourceId") or "").strip()
        if isinstance(release, Mapping) else ""
    )
    fallback_source_ids = {
        str(source.get("country") or "").strip().upper(): str(source.get("sourceId") or "").strip()
        for source in (release.get("fallbackSources", []) if isinstance(release, Mapping) else [])
        if isinstance(source, Mapping)
    }
    country_level_only = [
        {
            "country": country,
            "activeGeographyIds": sorted(country_active_ids[country]),
            "unavailableGeographyIds": sorted(unavailable_by_country[country]),
            "years": sorted(unavailable_years_by_country[country]),
            "reason": "population_unavailable_for_active_adm1",
            "sourceCoverage": {
                "availableGeographyCount": len(country_active_ids[country])
                - len(unavailable_by_country[country]),
                "unavailableGeographyCount": len(unavailable_by_country[country]),
                "populationArtifactFingerprint": population_artifact.get("buildFingerprint"),
                "sourceIds": sorted({
                    source_id for source_id in (
                        primary_source_id, fallback_source_ids.get(country, "")
                    ) if source_id
                }) or ["population-artifact"],
            },
        }
        for country in sorted(country_level_only_countries)
    ]
    population_values: dict[tuple[str, int], dict[str, Any]] = {}
    for row in population_rows:
        geography_id = str(row.get("geographyId") or "").strip()
        country = geography_country[geography_id]
        if country in country_level_only_countries:
            continue
        year = int(row.get("year"))
        key = (geography_id, year)
        if key in population_values:
            raise ValueError(f"duplicate population record: {geography_id} {year}")
        population_source_ids = _source_ids(
            row.get("sourceIds"), label=f"population {geography_id}"
        )
        population_values[key] = {
            "value": _finite_nonnegative(row.get("population"), label=f"population for {geography_id}"),
            "sourceIds": population_source_ids,
        }
    activity_values = _component_records(activity_records, component="activity", geography_country=geography_country)
    industrial_values = _component_records(industrial_records, component="industrial", geography_country=geography_country)
    activity_values = {
        key: value for key, value in activity_values.items()
        if geography_country[key[0]] not in country_level_only_countries
    }
    industrial_values = {
        key: value for key, value in industrial_values.items()
        if geography_country[key[0]] not in country_level_only_countries
    }
    for label, values in (("activity", activity_values), ("industrial", industrial_values)):
        unexpected = sorted(set(values) - set(population_values))
        if unexpected:
            geography_id, year = unexpected[0]
            raise ValueError(
                f"{label} record has no matching population geography-year: "
                f"{geography_id} {year}"
            )
    official_lineage: list[dict[str, Any]] = []
    official_keys: set[tuple[str, int]] = set()
    for raw in official_observations:
        geography_id = str(raw.get("geographyId") or raw.get("geography_id") or "").strip()
        if geography_id not in geography_country:
            raise ValueError(f"official observation uses unknown active ADM1 ID: {geography_id}")
        try:
            year = int(raw.get("year"))
        except (TypeError, ValueError) as error:
            raise ValueError("official observation requires a year") from error
        key = (geography_id, year)
        if geography_country[geography_id] in country_level_only_countries:
            continue
        if key not in population_values:
            raise ValueError(
                f"official observation has no matching population geography-year: "
                f"{geography_id} {year}"
            )
        if key in official_keys:
            raise ValueError(f"duplicate official observation: {geography_id} {year}")
        official_keys.add(key)
        country = str(raw.get("country") or geography_country[geography_id]).strip().upper()
        if country != geography_country[geography_id]:
            raise ValueError(f"official observation country mismatch for {geography_id}")
        value_kind = str(raw.get("valueKind") or raw.get("value_kind") or "").strip()
        if value_kind not in {"observed", "reported"}:
            raise ValueError("official observation lineage must be observed or reported")
        method_id = str(raw.get("methodId") or raw.get("method_id") or "").strip()
        if not method_id:
            raise ValueError("official observation lineage requires a method ID")
        official_lineage.append({
            "geographyId": geography_id,
            "country": country,
            "year": year,
            "sourceIds": _source_ids(
                raw.get("sourceIds") or raw.get("source_ids"),
                label=f"official observation {geography_id}",
            ),
            "methodId": method_id,
            "valueKind": value_kind,
        })
    official_lineage.sort(key=lambda row: (row["geographyId"], row["year"]))
    normalized_population = _normalize_component(population_values, geography_country=geography_country, label="population")
    normalized_activity = _normalize_component(activity_values, geography_country=geography_country, label="activity")
    normalized_industrial = _normalize_component(industrial_values, geography_country=geography_country, label="industrial")
    records: list[dict[str, Any]] = []
    for geography_id, year in sorted(population_values):
        sources = set(population_values[(geography_id, year)]["sourceIds"])
        for component_values in (activity_values, industrial_values):
            source = component_values.get((geography_id, year), {}).get("sourceId")
            if source:
                sources.add(str(source))
        records.append({
            "geographyId": geography_id,
            "country": geography_country[geography_id],
            "year": year,
            "populationShare": normalized_population[(geography_id, year)],
            "activityShare": normalized_activity.get((geography_id, year)),
            "industrialShare": normalized_industrial.get((geography_id, year)),
            "sourceIds": sorted(sources),
        })
    canonical_population_input = [
        {
            "geographyId": geography_id,
            "country": geography_country[geography_id],
            "year": year,
            "population": population_values[(geography_id, year)]["value"],
            "sourceIds": population_values[(geography_id, year)]["sourceIds"],
        }
        for geography_id, year in sorted(population_values)
    ]
    build_inputs = {
        "activeGeographyIds": active,
        "populationFingerprint": population_artifact.get("buildFingerprint")
        or _fingerprint(canonical_population_input),
        "activityFingerprint": _fingerprint(sorted(activity_values.items())),
        "industrialFingerprint": _fingerprint(sorted(industrial_values.items())),
        "officialObservationFingerprint": _fingerprint(official_lineage),
        "methodVersions": {
            "schema": SCHEMA_VERSION,
            "normalization": "country-component-share-v1",
            "allocation": ALLOCATION_METHOD_ID,
        },
    }
    artifact: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "publicDataOnly": True,
        "defaultComponentWeights": DEFAULT_COMPONENT_WEIGHTS,
        "sources": sorted(
            {source for row in records for source in row["sourceIds"]}
            | {source for row in official_lineage for source in row["sourceIds"]}
        ),
        "records": records,
        "countryLevelOnly": country_level_only,
        "officialObservationLineage": official_lineage,
        "buildInputs": build_inputs,
        "effectiveInputFingerprint": _fingerprint(build_inputs),
    }
    artifact["buildFingerprint"] = _fingerprint(artifact)
    validate_regional_demand_weights_artifact(artifact)
    return artifact


def validate_regional_demand_weights_artifact(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported regional demand weights schema")
    build_inputs = artifact.get("buildInputs")
    if not isinstance(build_inputs, Mapping):
        raise ValueError("regional demand weights require build inputs")
    if artifact.get("effectiveInputFingerprint") != _fingerprint(build_inputs):
        raise ValueError("regional demand weights effective-input fingerprint mismatch")
    seal_payload = dict(artifact)
    stored_seal = seal_payload.pop("buildFingerprint", None)
    if stored_seal != _fingerprint(seal_payload):
        raise ValueError("regional demand weights build fingerprint mismatch")
    active = set(_id_list(
        build_inputs.get("activeGeographyIds"),
        label="active ADM1 geography IDs",
    ))
    records = artifact.get("records")
    exceptions = artifact.get("countryLevelOnly", [])
    if not isinstance(records, list) or not isinstance(exceptions, list):
        raise ValueError("regional demand weights require records and country-level-only arrays")
    exception_countries: set[str] = set()
    exception_active_ids: set[str] = set()
    population_fingerprint = build_inputs.get("populationFingerprint")
    for entry in exceptions:
        if not isinstance(entry, Mapping):
            raise ValueError("invalid country-level-only exception")
        country = str(entry.get("country") or "").strip().upper()
        active_ids = set(_id_list(
            entry.get("activeGeographyIds"), label=f"country-level-only {country} active IDs"
        ))
        unavailable_ids = set(_id_list(
            entry.get("unavailableGeographyIds"),
            label=f"country-level-only {country} unavailable IDs",
        ))
        coverage = entry.get("sourceCoverage")
        if (
            re.fullmatch(r"[A-Z]{2}", country) is None
            or country in exception_countries
            or entry.get("reason") != "population_unavailable_for_active_adm1"
            or not unavailable_ids
            or not unavailable_ids.issubset(active_ids)
            or not active_ids.issubset(active)
            or exception_active_ids & active_ids
            or not isinstance(coverage, Mapping)
            or coverage.get("populationArtifactFingerprint") != population_fingerprint
            or not isinstance(coverage.get("sourceIds"), list)
            or not coverage.get("sourceIds")
            or any(not isinstance(value, str) or not value.strip() for value in coverage["sourceIds"])
            or coverage.get("availableGeographyCount") != len(active_ids - unavailable_ids)
            or coverage.get("unavailableGeographyCount") != len(unavailable_ids)
        ):
            raise ValueError("country-level-only exception requires an active unavailable population gap")
        years = entry.get("years")
        if (
            not isinstance(years, list)
            or not years
            or years != sorted(set(years))
            or any(isinstance(year, bool) or not isinstance(year, int) or year not in TARGET_YEARS for year in years)
        ):
            raise ValueError("country-level-only exception has invalid unavailable years")
        exception_countries.add(country)
        exception_active_ids.update(active_ids)
    record_ids: set[str] = set()
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("regional demand weight must be an object")
        geography_id = str(row.get("geographyId") or "").strip()
        country = str(row.get("country") or "").strip().upper()
        if geography_id in exception_active_ids or country in exception_countries:
            raise ValueError("country-level-only countries cannot contain regional rows")
        if geography_id not in active:
            raise ValueError("regional demand weight uses an inactive ADM1 ID")
        record_ids.add(geography_id)
    if record_ids | exception_active_ids != active:
        raise ValueError("regional demand weights must represent every active ADM1 ID")


def write_regional_demand_weights(artifact: Mapping[str, Any], output: Path | str) -> None:
    validate_regional_demand_weights_artifact(artifact)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_stable_json(artifact) + "\n", encoding="utf-8")
