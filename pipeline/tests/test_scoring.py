from grid_scope.scoring import score_infrastructure_demand


def test_infrastructure_demand_is_visible_weighted_sum() -> None:
    result = score_infrastructure_demand(
        {
            "compute_load_pressure": 88,
            "connection_scarcity": 84,
            "reinforcement_gap": 80,
            "firm_flexible_supply_gap": 60,
            "cooling_water_stress": 70,
        }
    )

    assert result.score == 78
    assert [item.max_points for item in result.contributions] == [25, 25, 20, 20, 10]
    assert sum(item.points for item in result.contributions) == result.score
    assert result.status == "rankable"


def test_missing_is_not_zero_and_can_make_region_unrankable() -> None:
    result = score_infrastructure_demand({"compute_load_pressure": 88})

    assert result.score is None
    assert result.coverage == 25
    assert result.status == "not_yet_rankable"


def test_rankable_requires_compute_and_grid_constraint() -> None:
    result = score_infrastructure_demand(
        {
            "firm_flexible_supply_gap": 90,
            "cooling_water_stress": 90,
            "reinforcement_gap": 90,
            "connection_scarcity": 90,
        }
    )

    assert result.coverage == 75
    assert result.score is None
