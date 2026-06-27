from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class ScoreResult:
    score: int | None
    coverage: int
    status: str
    contributions: list[ScoreContribution]


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
