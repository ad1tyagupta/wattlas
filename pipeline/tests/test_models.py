from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from grid_scope.models import (
    AssetProperties,
    ConnectorState,
    DemandRange,
    GeographyProperties,
    LensScores,
    RegionProperties,
    ValueKind,
)


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


def test_asset_supports_water_infrastructure_subtypes() -> None:
    asset = AssetProperties(
        id="asset-ae-desal-1",
        name="Example plant",
        geography_id="AE",
        category="water_infrastructure",
        subtype="desalination",
        lifecycle="under_construction",
        demand_mw=DemandRange(low=42, central=50, high=61),
        location_precision="city_centroid",
        value_kind="estimated",
        source_ids=["source-1"],
    )

    assert asset.category == "water_infrastructure"
    assert asset.subtype == "desalination"


def test_asset_rejects_demand_without_sources() -> None:
    with pytest.raises(ValidationError):
        AssetProperties(
            id="asset-us-dc-1",
            name="Uncited campus",
            geography_id="US",
            category="data_centre",
            subtype="hyperscale",
            lifecycle="announced",
            demand_mw=DemandRange(low=90, central=100, high=120),
            location_precision="region_centroid",
            value_kind="estimated",
            source_ids=[],
        )


def test_geography_has_country_peer_level() -> None:
    geography = GeographyProperties(
        id="AE",
        name="United Arab Emirates",
        country="AE",
        level="country",
        parent_id=None,
        score_year=2030,
        scores=LensScores(
            infrastructure_demand=72,
            site_attractiveness=68,
            system_risk=55,
        ),
        confidence=80,
        coverage=90,
        value_kind="reported",
        updated_at=datetime.now(UTC),
    )

    assert geography.peer_level == "country"
