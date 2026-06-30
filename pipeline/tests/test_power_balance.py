from __future__ import annotations

import json
from pathlib import Path

import pytest

from grid_scope.demand import annual_energy_from_average_mw
from grid_scope.models import DemandRange
from grid_scope.power_balance import (
    build_regional_energy_forecasts,
    calculate_power_balance,
    calculate_supply,
    derive_observed_capacity_factors,
    load_generation_assumptions,
)


ASSUMPTIONS_PATH = (
    Path(__file__).parents[2] / "data" / "curated" / "generation-assumptions.json"
)


def _plant(**overrides: object) -> dict:
    row = {
        "id": "plant-1",
        "geographyId": "US-CA",
        "countryIso3": "USA",
        "technology": "solar",
        "lifecycle": "operational",
        "capacityMw": {"low": 100, "central": 100, "high": 100},
        "capacityValueKind": "reported",
        "annualGenerationGwh": None,
        "commissioningYear": 2020,
        "retirementYear": None,
        "targetYear": None,
        "sourceIds": ["public-plant-registry"],
        "valueKind": "reported",
    }
    row.update(overrides)
    return row


@pytest.fixture
def assumptions() -> dict:
    return load_generation_assumptions(ASSUMPTIONS_PATH)


def test_reported_generation_wins_over_capacity_factor_estimate(assumptions: dict) -> None:
    supply = calculate_supply(
        [_plant(annualGenerationGwh={"low": 499, "central": 500, "high": 501})],
        year=2026,
        assumptions=assumptions,
    )

    assert supply["localGenerationGwh"] == {"low": 499.0, "central": 500.0, "high": 501.0}
    assert supply["generationComponents"][0]["valueKind"] == "reported"


def test_fully_reported_supply_does_not_claim_model_assumption_lineage(assumptions: dict) -> None:
    supply = calculate_supply(
        [_plant(
            annualGenerationGwh={"low": 499, "central": 500, "high": 501},
            dependableCapacityMw={"low": 15, "central": 20, "high": 25},
        )],
        year=2026,
        assumptions=assumptions,
    )

    assert supply["sourceIds"] == ["public-plant-registry"]
    assert supply["generationComponents"][0]["dependableMethod"] == "reported_dependable_capacity"


def test_estimated_generation_uses_capacity_factor_and_capacity_credit(assumptions: dict) -> None:
    supply = calculate_supply([_plant()], year=2026, assumptions=assumptions)

    solar = assumptions["technologies"]["solar"]
    assert supply["localGenerationGwh"] == pytest.approx(
        {
            "low": 100 * 8.76 * solar["capacityFactor"]["low"],
            "central": 100 * 8.76 * solar["capacityFactor"]["central"],
            "high": 100 * 8.76 * solar["capacityFactor"]["high"],
        }
    )
    assert supply["dependableCapacityMw"] == pytest.approx(
        {
            "low": 100 * solar["capacityCredit"]["low"],
            "central": 100 * solar["capacityCredit"]["central"],
            "high": 100 * solar["capacityCredit"]["high"],
        }
    )
    assert solar["capacityCredit"] != solar["capacityFactor"]


def test_observed_country_technology_factor_wins_only_when_adequate(assumptions: dict) -> None:
    observed = {
        "USA:solar": {
            "capacityFactor": {"low": 0.29, "central": 0.30, "high": 0.31},
            "years": 3,
            "capacityMw": 750,
            "sourceIds": ["eia-public"],
        }
    }
    preferred = calculate_supply(
        [_plant()], year=2026, assumptions=assumptions, observed_capacity_factors=observed
    )
    inadequate = calculate_supply(
        [_plant()],
        year=2026,
        assumptions=assumptions,
        observed_capacity_factors={
            "USA:solar": {**observed["USA:solar"], "years": 1, "capacityMw": 20}
        },
    )

    assert preferred["localGenerationGwh"]["central"] == pytest.approx(100 * 8.76 * 0.30)
    assert preferred["generationComponents"][0]["factorMethod"] == "country_technology_observed"
    assert preferred["confidence"] > inadequate["confidence"]
    assert inadequate["generationComponents"][0]["factorMethod"] == "global_technology_fallback"


def test_observed_country_technology_factors_are_derived_from_public_annual_totals() -> None:
    factors = derive_observed_capacity_factors([
        {
            "countryIso3": "USA", "technology": "solar", "year": 2023,
            "annualGenerationGwh": 175.2, "capacityMw": 100,
            "sourceIds": ["eia-public"],
        },
        {
            "countryIso3": "USA", "technology": "solar", "year": 2024,
            "annualGenerationGwh": 219, "capacityMw": 100,
            "sourceIds": ["eia-public"],
        },
    ])

    assert factors["USA:solar"]["capacityFactor"] == pytest.approx(
        {"low": 0.2, "central": 0.225, "high": 0.25}
    )
    assert factors["USA:solar"]["years"] == 2
    assert factors["USA:solar"]["capacityMw"] == 100
    assert factors["USA:solar"]["sourceIds"] == ["eia-public"]


def test_lifecycle_delivery_timing_and_retirement(assumptions: dict) -> None:
    plants = [
        _plant(id="operating"),
        _plant(id="construction", lifecycle="under_construction", targetYear=2028),
        _plant(id="planned", lifecycle="permitted", targetYear=2027),
        _plant(id="retired", retirementYear=2027),
        _plant(id="cancelled", lifecycle="cancelled"),
    ]

    before = calculate_supply(plants, year=2026, assumptions=assumptions)
    during = calculate_supply(plants, year=2027, assumptions=assumptions)
    after = calculate_supply(plants, year=2028, assumptions=assumptions)

    assert before["installedCapacityMw"] == pytest.approx(200)
    assert during["installedCapacityMw"] == pytest.approx(
        200 + 100 * assumptions["lifecycleDeliveryFactors"]["permitted"]
    )
    assert after["installedCapacityMw"] == pytest.approx(
        100
        + 100 * assumptions["lifecycleDeliveryFactors"]["permitted"]
        + 100 * assumptions["lifecycleDeliveryFactors"]["under_construction"]
    )
    assert "cancelled" not in {item["assetId"] for item in after["generationComponents"]}


def test_future_plant_uses_commissioning_year_when_target_year_is_unavailable(
    assumptions: dict,
) -> None:
    plant = _plant(
        lifecycle="under_construction", targetYear=None, commissioningYear=2028
    )

    assert calculate_supply([plant], year=2027, assumptions=assumptions)["installedCapacityMw"] == 0
    supply = calculate_supply([plant], year=2028, assumptions=assumptions)
    assert supply["installedCapacityMw"] == pytest.approx(
        100 * assumptions["lifecycleDeliveryFactors"]["under_construction"]
    )


def test_balance_keeps_local_gap_net_balance_and_observed_unmet_distinct() -> None:
    supply = {
        "localGenerationGwh": {"low": 700, "central": 800, "high": 900},
        "installedCapacityMw": 400,
        "dependableCapacityMw": {"low": 180, "central": 250, "high": 320},
        "sourceIds": ["public-supply"],
    }
    unknown = calculate_power_balance(
        demand_gwh={"low": 950, "central": 1_000, "high": 1_080},
        supply=supply,
        peak_demand_mw={"low": 280, "central": 300, "high": 330},
    )
    known = calculate_power_balance(
        demand_gwh={"low": 950, "central": 1_000, "high": 1_080},
        supply=supply,
        peak_demand_mw={"low": 280, "central": 300, "high": 330},
        net_interchange_gwh={"low": 95, "central": 100, "high": 105},
        observed_unmet_demand_gwh=7,
    )

    assert unknown["localGenerationGapGwh"] == {"low": 50.0, "central": 200.0, "high": 380.0}
    assert unknown["netBalanceGwh"] is None
    assert unknown["observedUnmetDemandGwh"] is None
    assert known["netBalanceGwh"] == {"low": -285.0, "central": -100.0, "high": 55.0}
    assert known["observedUnmetDemandGwh"] == 7.0


def test_forecasts_add_forward_infrastructure_once_and_preserve_order(assumptions: dict) -> None:
    base = [
        {
            "geographyId": "US-CA",
            "year": year,
            "demandGwh": {"low": 900 + year, "central": 1_000 + year, "high": 1_100 + year},
            "peakDemandMw": {"low": 200, "central": 220, "high": 250},
            "sourceIds": ["regional-demand-public"],
            "methodId": "regional-demand-forecast-v1",
            "confidence": 80,
            "coverage": 90,
        }
        for year in range(2026, 2032)
    ]
    increments = [
        {
            "incrementId": "dc-1",
            "geographyId": "US-CA",
            "targetYear": 2028,
            "demandGwh": {"low": 80, "central": 100, "high": 120},
            "sourceIds": ["dc-public"],
        },
        {
            "incrementId": "water-1",
            "geographyId": "US-CA",
            "targetYear": 2028,
            "demandGwh": {"low": 8, "central": 10, "high": 12},
            "sourceIds": ["water-public"],
        },
    ]
    forecasts = build_regional_energy_forecasts(
        geography_id="US-CA",
        demand_forecasts=base,
        demand_increments=increments,
        plants=[_plant()],
        assumptions=assumptions,
    )

    assert [row["year"] for row in forecasts] == list(range(2026, 2032))
    y2028 = next(row for row in forecasts if row["year"] == 2028)
    assert y2028["metrics"]["demandGwh"]["central"] == 1_000 + 2028 + 110
    assert y2028["appliedIncrementIds"] == ["dc-1", "water-1"]
    for row in forecasts:
        for value in (
            row["metrics"]["demandGwh"],
            row["metrics"]["localGenerationGwh"],
            row["metrics"]["localGenerationGapGwh"],
        ):
            assert value["low"] <= value["central"] <= value["high"]


def test_forward_asset_average_mw_is_annualized_to_gwh() -> None:
    result = annual_energy_from_average_mw(
        DemandRange(low=10, central=12, high=15)
    )

    assert result == DemandRange(low=87.6, central=105.12, high=131.4)
    with pytest.raises(ValueError, match="finite"):
        annual_energy_from_average_mw(
            DemandRange.model_construct(low=1, central=float("inf"), high=float("inf"))
        )


def test_assumption_loader_rejects_private_lineage_and_invalid_ranges(tmp_path: Path) -> None:
    payload = json.loads(ASSUMPTIONS_PATH.read_text())
    payload["technologies"]["solar"]["capacityFactor"]["central"] = float("nan")
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="finite"):
        load_generation_assumptions(invalid)

    payload = json.loads(ASSUMPTIONS_PATH.read_text())
    payload["sources"][0]["url"] = "file:///private/data.csv"
    private = tmp_path / "private.json"
    private.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="public HTTP"):
        load_generation_assumptions(private)

    payload = json.loads(ASSUMPTIONS_PATH.read_text())
    payload["sources"][0]["licence"] = "All rights reserved"
    proprietary = tmp_path / "proprietary.json"
    proprietary.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="redistributable"):
        load_generation_assumptions(proprietary)


def test_supply_rejects_malformed_physical_inputs(assumptions: dict) -> None:
    with pytest.raises(ValueError, match="capacity"):
        calculate_supply(
            [_plant(capacityMw={"low": -1, "central": 1, "high": 2})],
            year=2026,
            assumptions=assumptions,
        )
    with pytest.raises(ValueError, match="source"):
        calculate_supply([_plant(sourceIds=[])], year=2026, assumptions=assumptions)
    with pytest.raises(ValueError, match="year"):
        calculate_supply([_plant()], year=True, assumptions=assumptions)


def test_unavailable_supply_is_explicit_and_coverage_counts_missing_capacity(
    assumptions: dict,
) -> None:
    supply = calculate_supply(
        [_plant(id="known"), _plant(id="missing", capacityMw=None)],
        year=2026,
        assumptions=assumptions,
    )
    empty = calculate_supply([], year=2026, assumptions=assumptions)

    assert supply["coverage"] == 50
    assert empty["valueKind"] == "unavailable"
    assert empty["coverage"] == 0
    assert empty["sourceIds"] == ["ember-yearly-electricity-data", "nrel-atb-2024"]
