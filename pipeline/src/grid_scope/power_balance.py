from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from grid_scope.connectors.licensing import require_redistributable_licence
from grid_scope.models import PowerBalanceMetrics, RegionalEnergyForecast
from grid_scope.regional_demand import TARGET_YEARS, add_forward_demand_increments


SCHEMA_VERSION = "wattlas-generation-assumptions-v1"
SUPPLY_METHOD_ID = "regional-power-supply-v1"
BALANCE_METHOD_ID = "regional-power-balance-v1"
TECHNOLOGIES = {
    "solar", "wind", "hydro", "nuclear", "gas", "coal", "oil",
    "biomass", "geothermal", "other",
}
RANGE_PARTS = ("low", "central", "high")
EXCLUDED_LIFECYCLES = {"cancelled", "paused", "retired", "decommissioned", "shelved"}
FUTURE_LIFECYCLES = {"announced", "planning_filed", "permitted", "under_construction"}


def _number(value: object, *, label: str, nonnegative: bool = True) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a finite number") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    if nonnegative and result < 0:
        raise ValueError(f"{label} must be nonnegative")
    return result


def _finite_product(*values: float, label: str) -> float:
    result = 1.0
    for value in values:
        result *= value
        if not math.isfinite(result):
            raise ValueError(f"{label} must be finite")
    return result


def _finite_sum(values: Iterable[float], *, label: str) -> float:
    try:
        result = math.fsum(values)
    except OverflowError as error:
        raise ValueError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _finite_divide(numerator: float, denominator: float, *, label: str) -> float:
    if denominator == 0:
        raise ValueError(f"{label} denominator must be positive")
    result = numerator / denominator
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _year(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} year must be an integer")
    return value


def _range(
    value: object,
    *,
    label: str,
    nonnegative: bool = True,
) -> dict[str, float]:
    if isinstance(value, Mapping):
        if not all(part in value for part in RANGE_PARTS):
            raise ValueError(f"{label} requires low, central, and high")
        result = {
            part: _number(value[part], label=f"{label} {part}", nonnegative=nonnegative)
            for part in RANGE_PARTS
        }
    else:
        number = _number(value, label=label, nonnegative=nonnegative)
        result = {part: number for part in RANGE_PARTS}
    if not result["low"] <= result["central"] <= result["high"]:
        raise ValueError(f"{label} range must be ordered low <= central <= high")
    return result


def _source_ids(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} requires public source IDs")
    result: set[str] = set()
    for source_id in value:
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError(f"{label} requires nonblank public source IDs")
        result.add(source_id.strip())
    return sorted(result)


def _provenanced_metric(
    value: object,
    *,
    field: str,
    label: str,
    range_value: bool,
    signed: bool = False,
) -> tuple[dict[str, float] | float, dict[str, Any]]:
    if not isinstance(value, Mapping) or field not in value:
        raise ValueError(f"{label} provenance requires a metric record")
    source_ids = _source_ids(value.get("sourceIds"), label=f"{label} provenance")
    method_id = value.get("methodId")
    if not isinstance(method_id, str) or not method_id.strip():
        raise ValueError(f"{label} provenance requires a method ID")
    value_kind = str(value.get("valueKind") or "").strip()
    if value_kind not in {"observed", "reported"}:
        raise ValueError(f"{label} provenance must be observed or reported")
    metric = (
        _range(value[field], label=label, nonnegative=not signed)
        if range_value
        else _number(value[field], label=label, nonnegative=not signed)
    )
    return metric, {
        "sourceIds": source_ids,
        "methodId": method_id.strip(),
        "valueKind": value_kind,
    }


def load_generation_assumptions(path: Path | str) -> dict[str, Any]:
    """Load and validate the public, versioned supply-estimation assumptions."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported generation assumptions schema")
    if payload.get("publicDataOnly") is not True:
        raise ValueError("generation assumptions must be restricted to public data")
    if not isinstance(payload.get("methodId"), str) or not payload["methodId"].strip():
        raise ValueError("generation assumptions require a method ID")

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("generation assumptions require public sources")
    known_sources: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping):
            raise ValueError("generation assumption sources must be objects")
        source_id = str(source.get("id") or "").strip()
        url = str(source.get("url") or "").strip()
        licence = str(source.get("licence") or "").strip()
        parsed = urlparse(url)
        if not source_id or source_id in known_sources:
            raise ValueError("generation assumption source IDs must be unique and nonblank")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("generation assumptions require a public HTTP source URL")
        if not licence:
            raise ValueError("generation assumption sources require a licence")
        require_redistributable_licence(
            licence, label=f"generation assumption source {source_id}"
        )
        known_sources.add(source_id)

    adequacy = payload.get("observedFactorAdequacy")
    if not isinstance(adequacy, Mapping):
        raise ValueError("generation assumptions require observed-factor adequacy thresholds")
    minimum_years = _number(adequacy.get("minimumYears"), label="minimum observed years")
    minimum_capacity = _number(adequacy.get("minimumCapacityMw"), label="minimum observed capacity")
    if minimum_years < 1 or not minimum_years.is_integer():
        raise ValueError("minimum observed years must be a positive integer")
    if minimum_capacity <= 0:
        raise ValueError("minimum observed capacity must be positive")

    factors = payload.get("lifecycleDeliveryFactors")
    if not isinstance(factors, Mapping):
        raise ValueError("generation assumptions require lifecycle delivery factors")
    required_lifecycles = FUTURE_LIFECYCLES | {"operational"}
    if set(factors) != required_lifecycles:
        raise ValueError("generation assumptions have incomplete lifecycle delivery factors")
    for lifecycle, value in factors.items():
        factor = _number(value, label=f"{lifecycle} delivery factor")
        if factor > 1:
            raise ValueError("lifecycle delivery factors must be within 0-1")
    delivery_method = payload.get("lifecycleDeliveryFactorMethod")
    if not isinstance(delivery_method, Mapping):
        raise ValueError("generation assumptions require a delivery-factor method")
    delivery_source_ids = _source_ids(
        delivery_method.get("sourceIds"), label="delivery-factor method"
    )
    if not set(delivery_source_ids).issubset(known_sources):
        raise ValueError("delivery-factor method references an unknown source")
    if (
        not isinstance(delivery_method.get("methodNote"), str)
        or not delivery_method["methodNote"].strip()
    ):
        raise ValueError("generation assumptions require a delivery-factor method note")

    technologies = payload.get("technologies")
    if not isinstance(technologies, Mapping) or set(technologies) != TECHNOLOGIES:
        raise ValueError("generation assumptions require every supported technology")
    for technology, raw in technologies.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"{technology} assumptions must be an object")
        for field in ("capacityFactor", "capacityCredit"):
            values = _range(raw.get(field), label=f"{technology} {field}")
            if values["high"] > 1:
                raise ValueError(f"{technology} {field} must be within 0-1")
        ids = _source_ids(raw.get("sourceIds"), label=f"{technology} assumptions")
        if not set(ids).issubset(known_sources):
            raise ValueError(f"{technology} assumptions reference an unknown source")
        if not isinstance(raw.get("methodNote"), str) or not raw["methodNote"].strip():
            raise ValueError(f"{technology} assumptions require a method note")
    return deepcopy(payload)


def _observed_factor(
    *,
    country: str,
    technology: str,
    observed: Mapping[str, Mapping[str, Any]],
    assumptions: Mapping[str, Any],
) -> tuple[dict[str, float], list[str]] | None:
    raw = observed.get(f"{country}:{technology}")
    if raw is None:
        return None
    factor = _range(raw.get("capacityFactor"), label="observed capacity factor")
    if factor["high"] > 1:
        raise ValueError("observed capacity factor must be within 0-1")
    years = _number(raw.get("years"), label="observed capacity-factor years")
    capacity = _number(raw.get("capacityMw"), label="observed capacity-factor capacity")
    if years < 1 or not years.is_integer():
        raise ValueError("observed capacity-factor years must be a positive integer")
    source_ids = _source_ids(raw.get("sourceIds"), label="observed capacity factor")
    adequate = assumptions["observedFactorAdequacy"]
    if years < float(adequate["minimumYears"]) or capacity < float(adequate["minimumCapacityMw"]):
        return None
    return factor, source_ids


def derive_observed_capacity_factors(
    observations: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Derive country/technology factors from public annual generation and capacity."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, int]] = set()
    for raw in observations:
        country = str(raw.get("countryIso3") or "").strip().upper()
        technology = str(raw.get("technology") or "").strip()
        if len(country) != 3 or not country.isalpha():
            raise ValueError("observed capacity factors require an ISO3 country")
        if technology not in TECHNOLOGIES:
            raise ValueError(f"unsupported observed generation technology: {technology}")
        year = _year(raw.get("year"), label="observed capacity-factor")
        key = f"{country}:{technology}"
        if (key, year) in seen:
            raise ValueError(f"duplicate observed capacity-factor input: {key} {year}")
        seen.add((key, year))
        generation = _range(
            raw.get("annualGenerationGwh"), label=f"observed generation for {key} {year}"
        )["central"]
        capacity = _range(
            raw.get("capacityMw"), label=f"observed capacity for {key} {year}"
        )["central"]
        if capacity <= 0:
            raise ValueError("observed capacity-factor capacity must be positive")
        denominator = _finite_product(
            capacity, 8.76, label=f"observed capacity-factor denominator for {key} {year}"
        )
        factor = _finite_divide(
            generation, denominator, label=f"observed capacity factor for {key} {year}"
        )
        if factor < 0 or factor > 1:
            raise ValueError("derived observed capacity factor must be within 0-1")
        grouped.setdefault(key, []).append({
            "year": year,
            "generation": generation,
            "capacity": capacity,
            "factor": factor,
            "sourceIds": _source_ids(
                raw.get("sourceIds"), label=f"observed capacity-factor input {key} {year}"
            ),
        })

    result: dict[str, dict[str, Any]] = {}
    for key in sorted(grouped):
        rows = sorted(grouped[key], key=lambda row: row["year"])
        total_capacity = _finite_sum(
            (row["capacity"] for row in rows), label=f"observed capacity for {key}"
        )
        total_generation = _finite_sum(
            (row["generation"] for row in rows), label=f"observed generation for {key}"
        )
        factors = [row["factor"] for row in rows]
        result[key] = {
            "capacityFactor": {
                "low": min(factors),
                "central": _finite_divide(
                    total_generation,
                    _finite_product(
                        total_capacity, 8.76, label=f"observed denominator for {key}"
                    ),
                    label=f"observed aggregate capacity factor for {key}",
                ),
                "high": max(factors),
            },
            "years": len(rows),
            "capacityMw": _finite_divide(
                total_capacity, float(len(rows)), label=f"observed average capacity for {key}"
            ),
            "observationYears": [row["year"] for row in rows],
            "sourceIds": sorted({
                source_id for row in rows for source_id in row["sourceIds"]
            }),
            "methodId": "observed-country-technology-capacity-factor-v1",
        }
    return result


def _delivery_factor(plant: Mapping[str, Any], year: int, assumptions: Mapping[str, Any]) -> float:
    lifecycle = str(plant.get("lifecycle") or "").strip()
    raw_status = str(plant.get("rawStatus") or "").strip().lower()
    if lifecycle in EXCLUDED_LIFECYCLES or raw_status in EXCLUDED_LIFECYCLES:
        return 0.0
    retirement = plant.get("retirementYear")
    if retirement is not None and year > _year(retirement, label="retirement"):
        return 0.0
    if lifecycle == "operational":
        commissioning = plant.get("commissioningYear")
        if commissioning is not None and year < _year(commissioning, label="commissioning"):
            return 0.0
        return 1.0
    if lifecycle not in FUTURE_LIFECYCLES:
        raise ValueError(f"unsupported generation lifecycle: {lifecycle}")
    expected = plant.get("targetYear")
    if expected is None:
        expected = plant.get("commissioningYear")
    if expected is None:
        return 0.0
    if year < _year(expected, label="expected delivery"):
        return 0.0
    delivery_factors = assumptions.get("lifecycleDeliveryFactors")
    if not isinstance(delivery_factors, Mapping) or lifecycle not in delivery_factors:
        raise ValueError(f"missing {lifecycle} delivery factor")
    factor = _number(
        delivery_factors[lifecycle], label=f"{lifecycle} delivery factor"
    )
    if factor > 1:
        raise ValueError("lifecycle delivery factors must be within 0-1")
    return factor


def calculate_supply(
    plants: Iterable[Mapping[str, Any]],
    *,
    year: int,
    assumptions: Mapping[str, Any],
    observed_capacity_factors: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Calculate local annual generation and dependable capacity for one year."""

    target_year = _year(year, label="supply")
    technologies = assumptions.get("technologies")
    if not isinstance(technologies, Mapping) or not isinstance(
        assumptions.get("lifecycleDeliveryFactors"), Mapping
    ):
        raise ValueError("validated generation assumptions are required")
    delivery_factors = assumptions["lifecycleDeliveryFactors"]
    if set(delivery_factors) != FUTURE_LIFECYCLES | {"operational"}:
        raise ValueError("validated generation assumptions require every delivery factor")
    for lifecycle, raw_factor in delivery_factors.items():
        runtime_factor = _number(raw_factor, label=f"{lifecycle} delivery factor")
        if runtime_factor > 1:
            raise ValueError("lifecycle delivery factors must be within 0-1")
    adequacy = assumptions.get("observedFactorAdequacy")
    if not isinstance(adequacy, Mapping):
        raise ValueError("validated generation assumptions require adequacy thresholds")
    minimum_years = _number(adequacy.get("minimumYears"), label="minimum observed years")
    minimum_capacity = _number(
        adequacy.get("minimumCapacityMw"), label="minimum observed capacity"
    )
    if minimum_years < 1 or not minimum_years.is_integer() or minimum_capacity <= 0:
        raise ValueError("observed-factor adequacy thresholds must be positive")
    raw_assumption_sources = assumptions.get("sources")
    if not isinstance(raw_assumption_sources, list) or not raw_assumption_sources:
        raise ValueError("validated generation assumptions require public sources")
    assumption_source_ids = sorted({
        str(source.get("id") or "").strip()
        for source in raw_assumption_sources
        if isinstance(source, Mapping) and str(source.get("id") or "").strip()
    })
    if len(assumption_source_ids) != len(raw_assumption_sources):
        raise ValueError("validated generation assumptions have invalid source IDs")
    delivery_method_config = assumptions.get("lifecycleDeliveryFactorMethod")
    if not isinstance(delivery_method_config, Mapping):
        raise ValueError("validated generation assumptions require delivery-factor lineage")
    delivery_method_sources = _source_ids(
        delivery_method_config.get("sourceIds"), label="delivery-factor method"
    )
    if not set(delivery_method_sources).issubset(assumption_source_ids):
        raise ValueError("delivery-factor method references an unknown source")
    if (
        not isinstance(delivery_method_config.get("methodNote"), str)
        or not delivery_method_config["methodNote"].strip()
    ):
        raise ValueError("delivery-factor method requires a method note")
    observed = observed_capacity_factors or {}
    generation = {part: [] for part in RANGE_PARTS}
    dependable = {part: [] for part in RANGE_PARTS}
    installed: list[float] = []
    components: list[dict[str, Any]] = []
    all_sources: set[str] = set()
    generation_confidences: list[float] = []
    installed_confidences: list[float] = []
    dependable_confidences: list[float] = []
    installed_count = 0
    dependable_count = 0
    eligible_count = 0

    normalized = sorted((dict(plant) for plant in plants), key=lambda row: str(row.get("id") or ""))
    seen_ids: set[str] = set()
    for plant in normalized:
        asset_id = str(plant.get("id") or "").strip()
        if not asset_id or asset_id in seen_ids:
            raise ValueError("generation plants require unique nonblank IDs")
        seen_ids.add(asset_id)
        sources = _source_ids(plant.get("sourceIds"), label=f"generation plant {asset_id}")
        factor = _delivery_factor(plant, target_year, assumptions)
        if factor == 0:
            continue
        is_future_delivery = str(plant.get("lifecycle") or "") in FUTURE_LIFECYCLES
        delivery_confidence = 55.0 if is_future_delivery else 100.0
        eligible_count += 1
        all_sources.update(sources)
        technology = str(plant.get("technology") or "").strip()
        if technology not in technologies:
            raise ValueError(f"unsupported generation technology: {technology}")
        capacity_raw = plant.get("capacityMw")
        reported_generation_raw = plant.get("annualGenerationGwh")
        if capacity_raw is None and reported_generation_raw is None:
            continue
        capacity = (
            _range(capacity_raw, label=f"capacity for {asset_id}")
            if capacity_raw is not None else None
        )
        if capacity is not None:
            installed.append(_finite_product(
                capacity["central"], factor, label=f"installed capacity for {asset_id}"
            ))
            installed_count += 1
            capacity_kind = str(
                plant.get("capacityValueKind") or plant.get("valueKind") or ""
            )
            installed_confidences.append(
                min(
                    90.0 if capacity_kind in {"observed", "reported"} else 60.0,
                    delivery_confidence,
                )
            )
        technology_assumption = technologies[technology]
        if not isinstance(technology_assumption, Mapping):
            raise ValueError(f"invalid {technology} generation assumptions")
        technology_source_ids = _source_ids(
            technology_assumption.get("sourceIds"),
            label=f"{technology} generation assumptions",
        )
        if not set(technology_source_ids).issubset(assumption_source_ids):
            raise ValueError(f"{technology} assumptions reference an unknown source")

        if reported_generation_raw is not None:
            annual = _range(reported_generation_raw, label=f"reported generation for {asset_id}")
            annual = {
                part: _finite_product(
                    annual[part], factor, label=f"reported generation for {asset_id}"
                )
                for part in RANGE_PARTS
            }
            generation_kind = "reported"
            factor_method = "reported_annual_generation"
            generation_sources = sources
            confidence = 92.0
        else:
            assert capacity is not None
            country = str(plant.get("countryIso3") or plant.get("country") or "").strip().upper()
            preferred = _observed_factor(
                country=country,
                technology=technology,
                observed=observed,
                assumptions=assumptions,
            )
            if preferred is None:
                capacity_factor = _range(
                    technology_assumption.get("capacityFactor"),
                    label=f"{technology} capacity factor",
                )
                if capacity_factor["high"] > 1:
                    raise ValueError("capacity factors must be within 0-1")
                generation_sources = sorted(set(sources) | set(technology_source_ids))
                factor_method = "global_technology_fallback"
                confidence = 55.0
            else:
                capacity_factor, factor_sources = preferred
                generation_sources = sorted(set(sources) | set(factor_sources))
                factor_method = "country_technology_observed"
                confidence = 82.0
            annual = {
                part: _finite_product(
                    capacity[part], 8.76, capacity_factor[part], factor,
                    label=f"estimated generation for {asset_id}",
                )
                for part in RANGE_PARTS
            }
            generation_kind = "estimated"
        confidence = min(confidence, delivery_confidence)

        reported_dependable = plant.get("dependableCapacityMw")
        if reported_dependable is not None:
            dependable_range = _range(
                reported_dependable, label=f"reported dependable capacity for {asset_id}"
            )
            dependable_range = {
                part: _finite_product(
                    dependable_range[part], factor,
                    label=f"reported dependable capacity for {asset_id}",
                )
                for part in RANGE_PARTS
            }
            dependable_method = "reported_dependable_capacity"
            dependable_sources = sources
            dependable_confidence = 92.0
        elif capacity is not None:
            credit = _range(
                technology_assumption.get("capacityCredit"),
                label=f"{technology} capacity credit",
            )
            if credit["high"] > 1:
                raise ValueError("capacity credits must be within 0-1")
            dependable_range = {
                part: _finite_product(
                    capacity[part], credit[part], factor,
                    label=f"dependable capacity for {asset_id}",
                )
                for part in RANGE_PARTS
            }
            dependable_method = "technology_capacity_credit"
            dependable_sources = sorted(set(sources) | set(technology_source_ids))
            dependable_confidence = 55.0
        else:
            dependable_range = None
            dependable_method = "unavailable"
            dependable_sources = []
            dependable_confidence = 0.0
        dependable_confidence = min(dependable_confidence, delivery_confidence)

        for part in RANGE_PARTS:
            generation[part].append(annual[part])
            if dependable_range is not None:
                dependable[part].append(dependable_range[part])
        if dependable_range is not None:
            dependable_count += 1
            dependable_confidences.append(dependable_confidence)
        all_sources.update(generation_sources)
        all_sources.update(dependable_sources)
        delivery_method = delivery_method_config
        delivery_source_ids = (
            list(delivery_method_sources)
            if str(plant["lifecycle"]) in FUTURE_LIFECYCLES else []
        )
        all_sources.update(delivery_source_ids)
        generation_confidences.append(confidence)
        components.append({
            "assetId": asset_id,
            "technology": technology,
            "lifecycle": plant["lifecycle"],
            "deliveryFactor": factor,
            "deliveryFactorConfidence": delivery_confidence,
            "annualGenerationGwh": annual,
            "dependableCapacityMw": dependable_range,
            "valueKind": generation_kind,
            "factorMethod": factor_method,
            "dependableMethod": dependable_method,
            "sourceIds": sorted(
                set(generation_sources) | set(dependable_sources) | set(delivery_source_ids)
            ),
            "deliveryFactorSourceIds": delivery_source_ids,
            "deliveryFactorMethodNote": (
                delivery_method["methodNote"] if delivery_source_ids else None
            ),
        })

    has_generation = any(generation[part] for part in RANGE_PARTS)
    has_dependable = any(dependable[part] for part in RANGE_PARTS)
    metric_coverage = {
        "localGenerationGwh": (
            100.0 * len(components) / eligible_count if eligible_count else 0.0
        ),
        "installedCapacityMw": (
            100.0 * installed_count / eligible_count if eligible_count else 0.0
        ),
        "dependableCapacityMw": (
            100.0 * dependable_count / eligible_count if eligible_count else 0.0
        ),
    }
    metric_confidence = {
        "localGenerationGwh": (
            min(generation_confidences) if generation_confidences else 0.0
        ),
        "installedCapacityMw": (
            min(installed_confidences) if installed_confidences else 0.0
        ),
        "dependableCapacityMw": (
            min(dependable_confidences) if dependable_confidences else 0.0
        ),
    }
    return {
        "year": target_year,
        "installedCapacityMw": (
            _finite_sum(installed, label="total installed capacity") if installed else None
        ),
        "localGenerationGwh": (
            {
                part: _finite_sum(
                    generation[part], label=f"total local generation {part}"
                )
                for part in RANGE_PARTS
            }
            if has_generation else None
        ),
        "dependableCapacityMw": (
            {
                part: _finite_sum(
                    dependable[part], label=f"total dependable capacity {part}"
                )
                for part in RANGE_PARTS
            }
            if has_dependable else None
        ),
        "generationComponents": components,
        "methodId": str(assumptions.get("methodId") or SUPPLY_METHOD_ID),
        "sourceIds": sorted(all_sources),
        "metricConfidence": metric_confidence,
        "metricCoverage": metric_coverage,
        "confidence": min(metric_confidence.values()),
        "coverage": min(metric_coverage.values()),
        "valueKind": (
            "unavailable" if not components
            else "estimated" if any(row["valueKind"] == "estimated" for row in components)
            else "reported"
        ),
    }


def calculate_power_balance(
    *,
    demand_gwh: object,
    supply: Mapping[str, Any],
    peak_demand_mw: object,
    net_interchange_gwh: object | None = None,
    observed_unmet_demand_gwh: object | None = None,
) -> dict[str, Any]:
    """Keep local generation gap, known net balance, and observed unmet demand distinct."""

    demand = _range(demand_gwh, label="demand")
    peak = _range(peak_demand_mw, label="peak demand")
    generation_raw = supply.get("localGenerationGwh")
    generation = (
        None if generation_raw is None
        else _range(generation_raw, label="local generation")
    )
    dependable_raw = supply.get("dependableCapacityMw")
    dependable = (
        None if dependable_raw is None
        else _range(dependable_raw, label="dependable capacity")
    )
    installed_raw = supply.get("installedCapacityMw")
    installed = (
        None if installed_raw is None
        else _number(installed_raw, label="installed capacity")
    )
    local_gap = None
    if generation is not None:
        local_gap = {
            "low": _finite_sum(
                [demand["low"], -generation["high"]], label="local generation gap low"
            ),
            "central": _finite_sum(
                [demand["central"], -generation["central"]],
                label="local generation gap central",
            ),
            "high": _finite_sum(
                [demand["high"], -generation["low"]], label="local generation gap high"
            ),
        }
    net_balance = None
    metric_lineage: dict[str, dict[str, Any]] = {}
    if net_interchange_gwh is not None:
        interchange_raw, interchange_lineage = _provenanced_metric(
            net_interchange_gwh,
            field="netInterchangeGwh",
            label="net interchange",
            range_value=True,
            signed=True,
        )
        assert isinstance(interchange_raw, dict)
        metric_lineage["netInterchangeGwh"] = interchange_lineage
    else:
        interchange_raw = None
    if interchange_raw is not None and generation is not None:
        net_balance = {
            "low": _finite_sum(
                [generation["low"], interchange_raw["low"], -demand["high"]],
                label="net balance low",
            ),
            "central": _finite_sum(
                [
                    generation["central"],
                    interchange_raw["central"],
                    -demand["central"],
                ],
                label="net balance central",
            ),
            "high": _finite_sum(
                [generation["high"], interchange_raw["high"], -demand["low"]],
                label="net balance high",
            ),
        }
    if observed_unmet_demand_gwh is None:
        unmet = None
    else:
        unmet_raw, unmet_lineage = _provenanced_metric(
            observed_unmet_demand_gwh,
            field="observedUnmetDemandGwh",
            label="observed unmet demand",
            range_value=False,
        )
        assert isinstance(unmet_raw, float)
        unmet = unmet_raw
        metric_lineage["observedUnmetDemandGwh"] = unmet_lineage
    metrics = PowerBalanceMetrics(
        demand_gwh=demand,
        local_generation_gwh=generation,
        local_generation_gap_gwh=local_gap,
        net_balance_gwh=net_balance,
        observed_unmet_demand_gwh=unmet,
        installed_capacity_mw=installed,
        dependable_capacity_mw=dependable,
        peak_demand_mw=peak,
    )
    output = metrics.model_dump(by_alias=True)
    output["metricLineage"] = metric_lineage
    return output


def build_regional_energy_forecasts(
    *,
    geography_id: str,
    demand_forecasts: Iterable[Mapping[str, Any]],
    plants: Iterable[Mapping[str, Any]],
    assumptions: Mapping[str, Any],
    demand_increments: Iterable[Mapping[str, Any]] = (),
    observed_capacity_factors: Mapping[str, Mapping[str, Any]] | None = None,
    net_interchange_by_year: Mapping[int, object] | None = None,
    observed_unmet_by_year: Mapping[int, object] | None = None,
) -> list[dict[str, Any]]:
    """Build deterministic 2026-2031 balance records, applying each demand increment once."""

    region_id = geography_id.strip()
    if not region_id:
        raise ValueError("regional energy forecasts require a geography ID")
    demand_rows = add_forward_demand_increments(demand_forecasts, demand_increments)
    selected = [
        row
        for row in demand_rows
        if str(row.get("geographyId") or "").strip() == region_id
    ]
    years = [row.get("year") for row in selected]
    if years != list(TARGET_YEARS):
        raise ValueError(
            "regional energy forecasts require exactly one ordered record for 2026-2031"
        )
    plant_rows: list[dict[str, Any]] = []
    for raw_plant in plants:
        plant = dict(raw_plant)
        plant_geography = str(
            plant.get("geographyId") or plant.get("geography_id") or ""
        ).strip()
        if not plant_geography:
            raise ValueError("forecast power plants require a geography ID")
        if plant_geography == region_id:
            plant_rows.append(plant)
    output: list[dict[str, Any]] = []
    interchange = net_interchange_by_year or {}
    observed_unmet = observed_unmet_by_year or {}
    for demand in selected:
        year = int(demand["year"])
        source_ids = _source_ids(demand.get("sourceIds"), label=f"demand forecast {year}")
        supply = calculate_supply(
            plant_rows,
            year=year,
            assumptions=assumptions,
            observed_capacity_factors=observed_capacity_factors,
        )
        peak = demand.get("peakDemandMw")
        if peak is None:
            annual = _range(demand.get("demandGwh"), label=f"demand forecast {year}")
            peak = {
                part: _finite_divide(
                    annual[part], 8.76, label=f"derived peak demand {part} for {year}"
                )
                for part in RANGE_PARTS
            }
        metrics = calculate_power_balance(
            demand_gwh=demand.get("demandGwh"),
            supply=supply,
            peak_demand_mw=peak,
            net_interchange_gwh=interchange.get(year),
            observed_unmet_demand_gwh=observed_unmet.get(year),
        )
        metric_lineage = metrics.pop("metricLineage")
        metric_source_ids = {
            source_id
            for lineage in metric_lineage.values()
            for source_id in lineage["sourceIds"]
        }
        combined_sources = sorted(
            set(source_ids) | set(supply["sourceIds"]) | metric_source_ids
        )
        forecast = RegionalEnergyForecast(
            year=year,
            metrics=metrics,
            method_id=BALANCE_METHOD_ID,
            source_ids=combined_sources,
            confidence=min(
                _number(demand.get("confidence", 50), label="demand confidence"),
                supply["confidence"],
            ),
            coverage=min(
                _number(demand.get("coverage", 0), label="demand coverage"),
                supply["coverage"],
            ),
            value_kind=(
                "unavailable" if supply["valueKind"] == "unavailable" else "estimated"
            ),
        ).model_dump(by_alias=True, mode="json")
        forecast["geographyId"] = region_id
        forecast["appliedIncrementIds"] = sorted(demand.get("appliedIncrementIds") or [])
        forecast["metricLineage"] = metric_lineage
        output.append(forecast)
    return output
