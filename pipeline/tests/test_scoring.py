from grid_scope.scoring import (
    combine_asset_demand,
    lifecycle_timing_index,
    score_infrastructure_demand,
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


def test_combined_load_sums_mw_not_category_scores() -> None:
    assert combine_asset_demand(data_centre_mw=900, water_mw=100) == 1000


def test_lifecycle_timing_rewards_near_term_delivery() -> None:
    assert lifecycle_timing_index("under_construction", 2027) > lifecycle_timing_index("announced", 2031)
    assert lifecycle_timing_index("cancelled", 2027) == 0
