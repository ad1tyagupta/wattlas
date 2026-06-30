import math

import pytest

from pydantic import ValidationError

from grid_scope.models import LensScores, ScoreContribution
from grid_scope.scoring import (
    combine_asset_demand,
    lifecycle_timing_index,
    score_infrastructure_demand,
    score_power_balance,
)


def test_infrastructure_demand_uses_approved_weights() -> None:
    result = score_infrastructure_demand(
        projected_load_index=80,
        delivery_timing_index=60,
        local_load_shock_index=40,
    )

    assert result.score == 67
    assert [item.max_points for item in result.contributions] == [60, 15, 25]
    assert sum(item.points for item in result.contributions) == result.score
    assert result.status == "rankable"


def test_missing_is_not_zero_and_can_make_geography_unrankable() -> None:
    result = score_infrastructure_demand(projected_load_index=88)

    assert result.score is None
    assert result.coverage == 60
    assert result.status == "not_yet_rankable"


def test_confidence_does_not_change_demand_score() -> None:
    low_confidence = score_infrastructure_demand(
        projected_load_index=80,
        delivery_timing_index=60,
        local_load_shock_index=40,
        confidence=20,
    )
    high_confidence = score_infrastructure_demand(
        projected_load_index=80,
        delivery_timing_index=60,
        local_load_shock_index=40,
        confidence=95,
    )

    assert low_confidence.score == high_confidence.score == 67


def test_infrastructure_demand_canonicalizes_duplicate_source_ids() -> None:
    result = score_infrastructure_demand(
        projected_load_index=80,
        delivery_timing_index=60,
        local_load_shock_index=40,
        source_ids=[" source-b ", "source-a", "source-a"],
    )

    assert result.score == 67
    assert all(item.source_ids == ["source-a", "source-b"] for item in result.contributions)


def test_combined_load_sums_mw_not_category_scores() -> None:
    assert combine_asset_demand(data_centre_mw=900, water_mw=100) == 1000


def test_lifecycle_timing_rewards_near_term_delivery() -> None:
    assert lifecycle_timing_index("under_construction", 2027) > lifecycle_timing_index("announced", 2031)
    assert lifecycle_timing_index("cancelled", 2027) == 0


def test_power_balance_uses_approved_weights_and_metadata() -> None:
    result = score_power_balance(
        capacity_margin_index=80,
        local_balance_index=60,
        observed_unmet_demand_index=40,
        demand_growth_index=70,
        supply_delivery_index=50,
        source_ids=["source-b", "source-a", "source-a"],
    )

    assert result.score == pytest.approx(64)
    assert result.available_points == 100
    assert result.coverage == 100
    assert result.status == "rankable"
    assert [item.id for item in result.contributions] == [
        "capacity_margin",
        "annual_local_balance",
        "observed_unmet_demand",
        "forecast_demand_growth",
        "supply_delivery_gap",
    ]
    assert [item.max_points for item in result.contributions] == [35, 30, 15, 10, 10]
    for item in result.contributions:
        assert item.unit == "index"
        assert item.normalization
        assert item.method_version == "power-balance-score-1.0.0"
        assert item.source_ids == ["source-a", "source-b"]
    assert [item.value_kind for item in result.contributions] == [
        "estimated",
        "estimated",
        "observed",
        "estimated",
        "estimated",
    ]


def test_power_balance_missing_component_is_not_zero_and_exposes_denominator() -> None:
    result = score_power_balance(
        capacity_margin_index=80,
        local_balance_index=60,
        observed_unmet_demand_index=None,
        demand_growth_index=70,
        supply_delivery_index=50,
        source_ids=["source-a"],
    )

    assert result.available_points == 85
    assert result.coverage == 85
    assert result.score == pytest.approx((80 * 35 + 60 * 30 + 70 * 10 + 50 * 10) / 85)
    assert len(result.contributions) == 5
    unavailable = result.contributions[2]
    assert unavailable.raw_value is None
    assert unavailable.value_kind == "unavailable"
    assert unavailable.source_ids == []
    assert unavailable.points is None
    assert unavailable.max_points == 15
    assert unavailable.model_dump(by_alias=True)["points"] is None


def test_power_balance_withholds_score_below_sixty_weighted_points() -> None:
    result = score_power_balance(
        capacity_margin_index=90,
        local_balance_index=None,
        observed_unmet_demand_index=None,
        demand_growth_index=70,
        supply_delivery_index=50,
        source_ids=["source-a"],
    )

    assert result.available_points == 55
    assert result.score is None
    assert result.status == "not_yet_rankable"


@pytest.mark.parametrize("bad_value", [-0.01, 100.01, math.nan, math.inf, -math.inf])
def test_power_balance_rejects_nonfinite_or_out_of_range_indices(bad_value: float) -> None:
    with pytest.raises(ValueError, match="capacity_margin_index"):
        score_power_balance(capacity_margin_index=bad_value, source_ids=["source-a"])


@pytest.mark.parametrize("bad_value", [True, "50", object()])
def test_power_balance_rejects_non_numeric_indices(bad_value: object) -> None:
    with pytest.raises(ValueError, match="capacity_margin_index"):
        score_power_balance(capacity_margin_index=bad_value, source_ids=["source-a"])  # type: ignore[arg-type]


@pytest.mark.parametrize("source_ids", [None, [], [""], ["source-a", " "]])
def test_power_balance_requires_provenance_for_available_evidence(
    source_ids: list[str] | None,
) -> None:
    with pytest.raises(ValueError, match="source_ids"):
        score_power_balance(capacity_margin_index=50, source_ids=source_ids)


def test_power_balance_rejects_non_list_provenance() -> None:
    with pytest.raises(ValueError, match="source_ids"):
        score_power_balance(capacity_margin_index=50, source_ids="source-a")  # type: ignore[arg-type]


def test_power_balance_contributions_are_deterministic_and_lens_serializes_camel_case() -> None:
    first = score_power_balance(
        capacity_margin_index=80,
        local_balance_index=60,
        source_ids=["z", "a", "z"],
    )
    second = score_power_balance(
        capacity_margin_index=80,
        local_balance_index=60,
        source_ids=["a", "z"],
    )

    assert first.contributions == second.contributions
    assert LensScores(power_balance=64).model_dump(by_alias=True)["powerBalance"] == 64


def test_power_balance_trims_and_deduplicates_source_ids() -> None:
    result = score_power_balance(
        capacity_margin_index=80,
        local_balance_index=60,
        source_ids=[" source-b ", "source-a", "source-b", " source-a"],
    )

    available = [item for item in result.contributions if item.raw_value is not None]
    assert all(item.source_ids == ["source-a", "source-b"] for item in available)


@pytest.mark.parametrize("source_ids", ["source-a", 7, [7]])
def test_power_balance_validates_provenance_type_without_available_evidence(source_ids: object) -> None:
    with pytest.raises(ValueError, match="source_ids"):
        score_power_balance(source_ids=source_ids)  # type: ignore[arg-type]


@pytest.mark.parametrize("value_kind", ["not-a-value-kind", "estimated"])
def test_power_balance_rejects_invalid_value_kind_for_unavailable_component(
    value_kind: str,
) -> None:
    with pytest.raises(ValueError, match="capacity_margin"):
        score_power_balance(value_kinds={"capacity_margin": value_kind})


def test_observed_unmet_demand_cannot_be_labelled_as_estimated() -> None:
    with pytest.raises(ValueError, match="observed_unmet_demand"):
        score_power_balance(
            observed_unmet_demand_index=40,
            source_ids=["official-load-shedding"],
            value_kinds={"observed_unmet_demand": "estimated"},
        )


def test_contribution_rejects_zero_points_for_unavailable_evidence() -> None:
    with pytest.raises(ValidationError, match="unavailable score contribution"):
        ScoreContribution(
            id="missing",
            label="Missing",
            raw_value=None,
            unit="index",
            points=0,
            max_points=10,
            value_kind="unavailable",
            normalization="Unavailable",
            method_version="test-1",
        )


def test_contribution_rejects_null_points_for_available_evidence() -> None:
    with pytest.raises(ValidationError, match="available score contribution"):
        ScoreContribution(
            id="available",
            label="Available",
            raw_value=50,
            unit="index",
            points=None,
            max_points=10,
            value_kind="estimated",
            source_ids=["source-a"],
            normalization="Fixed threshold",
            method_version="test-1",
        )
