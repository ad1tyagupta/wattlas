import pytest

from grid_scope.demand import combine_demand, data_centre_demand, water_demand
from grid_scope.models import DemandRange


def test_it_capacity_uses_pue_range() -> None:
    result = data_centre_demand(it_capacity_mw=100, reported_grid_mw=None)

    assert result == DemandRange(low=120, central=130, high=150)


def test_reported_grid_capacity_takes_precedence() -> None:
    result = data_centre_demand(it_capacity_mw=100, reported_grid_mw=180)

    assert result == DemandRange(low=180, central=180, high=180)


def test_desalination_uses_throughput_and_energy_intensity() -> None:
    result = water_demand(
        subtype="desalination",
        throughput_m3_day=500_000,
        intensity_kwh_m3=DemandRange(low=2.8, central=3.5, high=4.2),
    )

    assert result is not None
    assert result.central == pytest.approx(72.9167, rel=1e-3)


@pytest.mark.parametrize("subtype", ["wastewater", "water_reuse", "pipeline_pumping"])
def test_flow_driven_water_assets_have_versioned_defaults(subtype: str) -> None:
    result = water_demand(subtype=subtype, throughput_m3_day=100_000)

    assert result is not None
    assert result.low <= result.central <= result.high


def test_passive_reservoir_has_no_demand_without_pumping() -> None:
    assert water_demand(subtype="reservoir", throughput_m3_day=None) is None


def test_combined_demand_adds_electrical_ranges() -> None:
    result = combine_demand(
        DemandRange(low=80, central=100, high=120),
        DemandRange(low=10, central=20, high=30),
    )

    assert result == DemandRange(low=90, central=120, high=150)


def test_conversion_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError):
        data_centre_demand(it_capacity_mw=-1, reported_grid_mw=None)
