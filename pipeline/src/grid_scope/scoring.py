from __future__ import annotations

from dataclasses import dataclass

from grid_scope.models import ScoreContribution, ValueKind


@dataclass(frozen=True)
class DriverDefinition:
    id: str
    label: str
    weight: int


DRIVERS = (
    DriverDefinition("compute_load_pressure", "Compute-load pressure", 25),
    DriverDefinition("connection_scarcity", "Connection scarcity", 25),
    DriverDefinition("reinforcement_gap", "Grid-reinforcement gap", 20),
    DriverDefinition("firm_flexible_supply_gap", "Firm and flexible supply gap", 20),
    DriverDefinition("cooling_water_stress", "Cooling and water stress", 10),
)


@dataclass(frozen=True)
class ScoreResult:
    score: int | None
    coverage: int
    status: str
    contributions: list[ScoreContribution]


def score_infrastructure_demand(values: dict[str, float | None]) -> ScoreResult:
    contributions: list[ScoreContribution] = []
    coverage = 0
    for driver in DRIVERS:
        raw_value = values.get(driver.id)
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
                source_ids=[],
                normalization="Fixed 0–100 driver threshold, model 1.0.0",
            )
        )
        coverage += driver.weight

    has_compute = values.get("compute_load_pressure") is not None
    has_grid_constraint = any(
        values.get(driver_id) is not None
        for driver_id in ("connection_scarcity", "reinforcement_gap")
    )
    rankable = coverage >= 60 and has_compute and has_grid_constraint
    score = round(sum(item.points for item in contributions)) if rankable else None
    return ScoreResult(
        score=score,
        coverage=coverage,
        status="rankable" if rankable else "not_yet_rankable",
        contributions=contributions,
    )
