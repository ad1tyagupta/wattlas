from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from grid_scope.models import ConnectorState, LensScores, RegionProperties, ValueKind


def test_region_rejects_score_outside_range() -> None:
    with pytest.raises(ValidationError):
        RegionProperties(
            id="DE71",
            name="Darmstadt",
            country="DE",
            score_year=2030,
            scores=LensScores(
                infrastructure_demand=101,
                site_attractiveness=60,
                system_risk=40,
            ),
            confidence=72,
            coverage=76,
            value_kind=ValueKind.ESTIMATED,
            updated_at=datetime.now(UTC),
        )


def test_connector_state_names_are_stable() -> None:
    assert {state.value for state in ConnectorState} == {
        "current",
        "cached",
        "stale",
        "failed",
        "not_configured",
    }


def test_region_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        RegionProperties(
            id="DE71",
            name="Darmstadt",
            country="DE",
            score_year=2030,
            scores=LensScores(
                infrastructure_demand=78,
                site_attractiveness=60,
                system_risk=40,
            ),
            confidence=72,
            coverage=76,
            value_kind=ValueKind.ESTIMATED,
            updated_at=datetime(2026, 6, 27, 4, 12),
        )
