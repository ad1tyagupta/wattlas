from __future__ import annotations

import math

from grid_scope.models import DemandRange


MODEL_VERSION = "demand-conversion-1.0.0"
DEFAULT_PUE = DemandRange(low=1.2, central=1.3, high=1.5)
WATER_INTENSITY_KWH_M3 = {
    "desalination": DemandRange(low=2.8, central=3.5, high=4.2),
    "wastewater": DemandRange(low=0.3, central=0.6, high=1.2),
    "water_reuse": DemandRange(low=0.8, central=1.2, high=1.8),
    "pipeline_pumping": DemandRange(low=0.15, central=0.45, high=0.9),
}


def _require_nonnegative(value: float | None, label: str) -> None:
    if value is not None and (
        isinstance(value, bool) or not math.isfinite(value) or value < 0
    ):
        raise ValueError(f"{label} must be a finite nonnegative number")


def data_centre_demand(
    *,
    it_capacity_mw: float | None,
    reported_grid_mw: float | None,
    pue: DemandRange = DEFAULT_PUE,
) -> DemandRange | None:
    """Convert public data-centre capacity into facility electrical demand."""
    _require_nonnegative(it_capacity_mw, "IT capacity")
    _require_nonnegative(reported_grid_mw, "reported grid capacity")
    if reported_grid_mw is not None:
        return DemandRange(
            low=reported_grid_mw,
            central=reported_grid_mw,
            high=reported_grid_mw,
        )
    if it_capacity_mw is None:
        return None
    return DemandRange(
        low=round(it_capacity_mw * pue.low, 6),
        central=round(it_capacity_mw * pue.central, 6),
        high=round(it_capacity_mw * pue.high, 6),
    )


def water_demand(
    *,
    subtype: str,
    throughput_m3_day: float | None,
    intensity_kwh_m3: DemandRange | None = None,
    reported_electrical_mw: float | None = None,
) -> DemandRange | None:
    """Convert flow and energy intensity into average electrical demand."""
    _require_nonnegative(throughput_m3_day, "water throughput")
    _require_nonnegative(reported_electrical_mw, "reported electrical demand")
    if reported_electrical_mw is not None:
        return DemandRange(
            low=reported_electrical_mw,
            central=reported_electrical_mw,
            high=reported_electrical_mw,
        )
    if throughput_m3_day is None:
        return None
    intensity = intensity_kwh_m3 or WATER_INTENSITY_KWH_M3.get(subtype)
    if intensity is None:
        return None
    return DemandRange(
        low=round(throughput_m3_day * intensity.low / 24_000, 6),
        central=round(throughput_m3_day * intensity.central / 24_000, 6),
        high=round(throughput_m3_day * intensity.high / 24_000, 6),
    )


def combine_demand(*ranges: DemandRange | None) -> DemandRange | None:
    present = [item for item in ranges if item is not None]
    if not present:
        return None
    return DemandRange(
        low=round(sum(item.low for item in present), 6),
        central=round(sum(item.central for item in present), 6),
        high=round(sum(item.high for item in present), 6),
    )


def annual_energy_from_average_mw(demand_mw: DemandRange) -> DemandRange:
    """Convert an average electrical-demand range in MW to annual GWh."""

    for part in ("low", "central", "high"):
        _require_nonnegative(getattr(demand_mw, part), f"average demand {part}")
    return DemandRange(
        low=round(demand_mw.low * 8.76, 6),
        central=round(demand_mw.central * 8.76, 6),
        high=round(demand_mw.high * 8.76, 6),
    )
