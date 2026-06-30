from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Mapping

from grid_scope.models import ScoreContribution, ValueKind


@dataclass(frozen=True)
class DriverDefinition:
    id: str
    label: str
    weight: int


DRIVERS = (
    DriverDefinition("projected_load", "Projected electrical load", 60),
    DriverDefinition("delivery_timing", "Delivery timing", 15),
    DriverDefinition("local_load_shock", "Local load shock", 25),
)

POWER_BALANCE_METHOD_VERSION = "power-balance-score-1.0.0"
POWER_BALANCE_MINIMUM_COVERAGE = 60

POWER_BALANCE_DRIVERS = (
    DriverDefinition("capacity_margin", "Dependable-capacity margin", 35),
    DriverDefinition("annual_local_balance", "Annual local generation balance", 30),
    DriverDefinition("observed_unmet_demand", "Observed unmet demand", 15),
    DriverDefinition("forecast_demand_growth", "Forecast demand growth", 10),
    DriverDefinition("supply_delivery_gap", "Supply delivery gap", 10),
)

POWER_BALANCE_NORMALIZATIONS = {
    "capacity_margin": "Capacity-margin pressure normalized to a 0–100 index",
    "annual_local_balance": "Annual local-balance pressure normalized to a 0–100 index",
    "observed_unmet_demand": "Observed unmet-demand pressure normalized to a 0–100 index",
    "forecast_demand_growth": "Forecast demand-growth pressure normalized to a 0–100 index",
    "supply_delivery_gap": "Supply delivery-gap pressure normalized to a 0–100 index",
}


@dataclass(frozen=True)
class ScoreResult:
    score: float | None
    coverage: int
    status: str
    contributions: list[ScoreContribution]
    available_points: int


def score_infrastructure_demand(
    *,
    projected_load_index: float | None = None,
    delivery_timing_index: float | None = None,
    local_load_shock_index: float | None = None,
    confidence: float | None = None,
    source_ids: list[str] | None = None,
) -> ScoreResult:
    """Score demand without allowing confidence to alter the estimate."""
    del confidence
    values = {
        "projected_load": projected_load_index,
        "delivery_timing": delivery_timing_index,
        "local_load_shock": local_load_shock_index,
    }
    contributions: list[ScoreContribution] = []
    coverage = 0
    for driver in DRIVERS:
        raw_value = values[driver.id]
        if raw_value is None:
            continue
        normalized = max(0.0, min(100.0, float(raw_value)))
        points = round(normalized * driver.weight / 100, 1)
        contributions.append(
            ScoreContribution(
                id=driver.id,
                label=driver.label,
                raw_value=raw_value,
                unit="index",
                points=points,
                max_points=driver.weight,
                value_kind=ValueKind.ESTIMATED,
                source_ids=source_ids or [],
                normalization="Fixed 0–100 threshold, Wattlas model 2.0.0",
                method_version="infrastructure-demand-score-2.0.0",
            )
        )
        coverage += driver.weight

    rankable = (
        coverage == 100
        and projected_load_index is not None
        and local_load_shock_index is not None
    )
    score = round(sum(item.points for item in contributions)) if rankable else None
    return ScoreResult(
        score=score,
        coverage=coverage,
        status="rankable" if rankable else "not_yet_rankable",
        contributions=contributions,
        available_points=coverage,
    )


def score_power_balance(
    *,
    capacity_margin_index: float | None = None,
    local_balance_index: float | None = None,
    observed_unmet_demand_index: float | None = None,
    demand_growth_index: float | None = None,
    supply_delivery_index: float | None = None,
    source_ids: list[str] | None = None,
    value_kinds: Mapping[str, ValueKind | str] | None = None,
) -> ScoreResult:
    """Calculate explainable supply-pressure points from available evidence only."""
    values = {
        "capacity_margin": capacity_margin_index,
        "annual_local_balance": local_balance_index,
        "observed_unmet_demand": observed_unmet_demand_index,
        "forecast_demand_growth": demand_growth_index,
        "supply_delivery_gap": supply_delivery_index,
    }
    parameter_names = {
        "capacity_margin": "capacity_margin_index",
        "annual_local_balance": "local_balance_index",
        "observed_unmet_demand": "observed_unmet_demand_index",
        "forecast_demand_growth": "demand_growth_index",
        "supply_delivery_gap": "supply_delivery_index",
    }
    unknown_value_kinds = set(value_kinds or {}) - set(values)
    if unknown_value_kinds:
        raise ValueError(f"unknown Power Balance value-kind IDs: {sorted(unknown_value_kinds)}")

    available = any(value is not None for value in values.values())
    if available and (
        not isinstance(source_ids, list)
        or not source_ids
        or any(not isinstance(source_id, str) or not source_id.strip() for source_id in source_ids)
    ):
        raise ValueError("source_ids must contain nonblank provenance for available evidence")
    canonical_source_ids = sorted(set(source_ids or []))

    contributions: list[ScoreContribution] = []
    available_points = 0
    weighted_pressure = 0.0
    for driver in POWER_BALANCE_DRIVERS:
        raw_value = values[driver.id]
        if raw_value is None:
            contributions.append(
                ScoreContribution(
                    id=driver.id,
                    label=driver.label,
                    raw_value=None,
                    unit="index",
                    points=0,
                    max_points=driver.weight,
                    value_kind=ValueKind.UNAVAILABLE,
                    source_ids=[],
                    normalization=POWER_BALANCE_NORMALIZATIONS[driver.id],
                    method_version=POWER_BALANCE_METHOD_VERSION,
                )
            )
            continue

        if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
            raise ValueError(f"{parameter_names[driver.id]} must be a finite number from 0 to 100")
        normalized = float(raw_value)
        if not math.isfinite(normalized) or not 0 <= normalized <= 100:
            raise ValueError(f"{parameter_names[driver.id]} must be a finite number from 0 to 100")

        default_value_kind = (
            ValueKind.OBSERVED
            if driver.id == "observed_unmet_demand"
            else ValueKind.ESTIMATED
        )
        try:
            value_kind = ValueKind((value_kinds or {}).get(driver.id, default_value_kind))
        except ValueError as exc:
            raise ValueError(f"invalid value kind for {driver.id}") from exc
        if value_kind == ValueKind.UNAVAILABLE:
            raise ValueError(f"available {driver.id} evidence cannot have unavailable value kind")
        if driver.id == "observed_unmet_demand" and value_kind not in {
            ValueKind.OBSERVED,
            ValueKind.REPORTED,
        }:
            raise ValueError("observed_unmet_demand must be observed or reported evidence")
        points = normalized * driver.weight / 100
        contributions.append(
            ScoreContribution(
                id=driver.id,
                label=driver.label,
                raw_value=normalized,
                unit="index",
                points=points,
                max_points=driver.weight,
                value_kind=value_kind,
                source_ids=canonical_source_ids,
                normalization=POWER_BALANCE_NORMALIZATIONS[driver.id],
                method_version=POWER_BALANCE_METHOD_VERSION,
            )
        )
        available_points += driver.weight
        weighted_pressure += normalized * driver.weight

    rankable = available_points >= POWER_BALANCE_MINIMUM_COVERAGE
    score = weighted_pressure / available_points if rankable else None
    return ScoreResult(
        score=score,
        coverage=available_points,
        status="rankable" if rankable else "not_yet_rankable",
        contributions=contributions,
        available_points=available_points,
    )


def combine_asset_demand(*, data_centre_mw: float | None, water_mw: float | None) -> float | None:
    present = [value for value in (data_centre_mw, water_mw) if value is not None]
    return sum(present) if present else None


def lifecycle_timing_index(lifecycle: str, target_year: int | None) -> int:
    lifecycle_weight = {
        "operational": 100,
        "under_construction": 92,
        "permitted": 78,
        "planning_filed": 62,
        "announced": 48,
        "paused": 20,
        "cancelled": 0,
    }.get(lifecycle, 0)
    if lifecycle_weight == 0 or target_year is None:
        return lifecycle_weight
    year_weight = {2026: 100, 2027: 92, 2028: 82, 2029: 70, 2030: 58, 2031: 46}.get(target_year, 0)
    return round(0.65 * lifecycle_weight + 0.35 * year_weight)
