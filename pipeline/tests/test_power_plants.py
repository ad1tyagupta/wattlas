from __future__ import annotations

from copy import deepcopy

import pytest

from grid_scope.models import AssetProperties
from grid_scope.power_plants import SOURCE_RANK, canonicalize_power_plants


def power_record(**overrides: object) -> dict:
    record = {
        "id": "gem-plant-alpha",
        "name": "Alpha Power Station",
        "plantName": "Alpha Power Station",
        "category": "power_generation",
        "technology": "gas",
        "primaryFuel": "Natural gas",
        "secondaryFuel": None,
        "lifecycle": "operational",
        "rawStatus": "Operating",
        "capacityMw": {"low": 98.0, "central": 100.0, "high": 102.0},
        "capacityValueKind": "reported",
        "plantId": "gem-plant-alpha",
        "unitId": None,
        "externalIds": {"gemPlant": "GEM-ALPHA"},
        "country": "US",
        "geographyId": "US",
        "coordinates": [-90.0, 35.0],
        "locationPrecision": "exact",
        "operator": "Alpha Energy",
        "sourceIds": ["gem-gipt"],
        "sourceType": "research_verified",
        "valueKind": "reported",
        "evidence": [{"id": "gem-alpha", "sourceId": "gem-gipt"}],
    }
    record.update(overrides)
    return record


def test_source_precedence_is_the_approved_four_tier_order() -> None:
    assert SOURCE_RANK == {
        "official_verified": 4,
        "research_verified": 3,
        "community_mapped": 2,
        "modelled": 1,
    }


def test_shared_strong_identity_merges_sources_but_namespaces_remain_safe() -> None:
    gem = power_record(externalIds={"gemPlant": "G-1", "wikidata": "Q123"})
    wri = power_record(
        id="wri-plant-1",
        name="Alpha Generating Station",
        plantName="Alpha Generating Station",
        externalIds={"wri": "W-1", "wikidata": "Q123"},
        sourceIds=["wri-gppd"],
        evidence=[{"id": "wri-alpha", "sourceId": "wri-gppd"}],
    )
    osm = power_record(
        id="osm-power-way-1",
        name="Alpha electricity works",
        plantName="Alpha electricity works",
        externalIds={"osm": "way/1", "wikidata": "Q123"},
        sourceIds=["osm-power"],
        sourceType="community_mapped",
        evidence=[{"id": "osm-alpha", "sourceId": "osm-power"}],
    )

    merged = canonicalize_power_plants([osm, wri, gem])

    assert len(merged["records"]) == 1
    record = merged["records"][0]
    assert record["externalIds"] == {
        "gemPlant": "G-1",
        "osm": "way/1",
        "wikidata": "Q123",
        "wri": "W-1",
    }
    assert record["sourceIds"] == ["gem-gipt", "osm-power", "wri-gppd"]

    different_namespaces = canonicalize_power_plants([
        power_record(id="first", externalIds={"gemPlant": "777"}),
        power_record(
            id="second",
            externalIds={"wri": "777"},
            name="Unrelated Solar Park",
            plantName="Unrelated Solar Park",
            operator="Other Energy",
            coordinates=[20.0, 10.0],
        ),
    ])
    assert len(different_namespaces["records"]) == 2


def test_conservative_fuzzy_match_requires_name_operator_location_and_capacity() -> None:
    first = power_record(externalIds={}, name="Alpha Power Plant")
    duplicate = power_record(
        id="official-alpha",
        plantId="official-alpha",
        externalIds={},
        name="Alpha Power Station",
        coordinates=[-90.006, 35.004],
        capacityMw={"low": 100.0, "central": 103.0, "high": 105.0},
        sourceIds=["official-us"],
        sourceType="official_verified",
    )
    uncertain_colocated = power_record(
        id="beta",
        plantId="beta",
        externalIds={},
        name="Beta Power Station",
        plantName="Beta Power Station",
        coordinates=[-90.003, 35.002],
    )

    result = canonicalize_power_plants([uncertain_colocated, duplicate, first])

    assert len(result["records"]) == 2
    assert any(sorted(record["sourceIds"]) == ["gem-gipt", "official-us"] for record in result["records"])


def test_units_stay_addressable_and_roll_up_without_double_counting_plant_records() -> None:
    first_unit = power_record(
        id="gem-unit-1",
        name="Alpha Unit 1",
        plantName="Alpha Power Station",
        unitId="gem-unit-1",
        externalIds={"gemPlant": "GEM-ALPHA", "gemUnit": "GEM-U-1"},
        capacityMw={"low": 60.0, "central": 60.0, "high": 60.0},
    )
    second_unit = power_record(
        id="gem-unit-2",
        name="Alpha Unit 2",
        plantName="Alpha Power Station",
        unitId="gem-unit-2",
        externalIds={"gemPlant": "GEM-ALPHA", "gemUnit": "GEM-U-2"},
        capacityMw={"low": 40.0, "central": 40.0, "high": 40.0},
    )
    plant_level_duplicate = power_record(
        id="wri-alpha",
        plantId="wri-alpha",
        externalIds={"gemPlant": "GEM-ALPHA", "wri": "WRI-ALPHA"},
        capacityMw={"low": 100.0, "central": 100.0, "high": 100.0},
        sourceIds=["wri-gppd"],
    )

    result = canonicalize_power_plants([plant_level_duplicate, second_unit, first_unit])

    assert [unit["unitId"] for unit in result["units"]] == ["gem-unit-1", "gem-unit-2"]
    assert len(result["records"]) == 3
    assert len(result["plants"]) == 1
    plant = result["plants"][0]
    assert plant["unitCount"] == 2
    assert plant["recordCount"] == 3
    assert plant["operatingCapacityMw"]["central"] == 100.0
    assert plant["operatingCapacityMwByTechnology"] == {"gas": 100.0}


def test_shared_plant_wikidata_does_not_collapse_distinct_units() -> None:
    first = power_record(
        id="gem-unit-1",
        unitId="gem-unit-1",
        externalIds={"gemPlant": "G-1", "gemUnit": "U-1", "wikidata": "Q-PLANT"},
    )
    second = power_record(
        id="gem-unit-2",
        unitId="gem-unit-2",
        externalIds={"gemPlant": "G-1", "gemUnit": "U-2", "wikidata": "Q-PLANT"},
    )

    result = canonicalize_power_plants([first, second])

    assert len(result["units"]) == 2
    assert result["plants"][0]["unitCount"] == 2


def test_precedence_is_field_specific_and_reported_values_beat_estimates() -> None:
    community = power_record(
        id="osm-alpha",
        name="Community Alpha",
        externalIds={"wikidata": "Q42", "osm": "way/42"},
        operator="Community operator detail",
        capacityMw={"low": 88.0, "central": 90.0, "high": 92.0},
        capacityValueKind="reported",
        sourceIds=["osm-power"],
        sourceType="community_mapped",
    )
    official = power_record(
        id="official-alpha",
        name="Official Alpha Energy Centre",
        externalIds={"wikidata": "Q42", "official": "OFF-42"},
        operator=None,
        capacityMw={"low": 95.0, "central": 100.0, "high": 110.0},
        capacityValueKind="estimated",
        sourceIds=["official-registry"],
        sourceType="official_verified",
        valueKind="estimated",
    )

    record = canonicalize_power_plants([official, community])["records"][0]

    assert record["name"] == "Official Alpha Energy Centre"
    assert record["operator"] == "Community operator detail"
    assert record["capacityMw"]["central"] == 90.0
    assert record["capacityValueKind"] == "reported"
    assert record["fieldProvenance"]["capacityMw"]["sourceType"] == "community_mapped"


def test_combined_lineage_aliases_and_evidence_are_deterministic() -> None:
    first = power_record(
        name="Alpha Plant",
        externalIds={"wikidata": "Q9", "gemPlant": "G9"},
        evidence=[{"id": "z", "sourceId": "gem-gipt"}],
    )
    second = power_record(
        id="official-nine",
        name="Alpha Energy Centre",
        externalIds={"wikidata": "Q9", "official": "O9"},
        evidence=[{"id": "a", "sourceId": "official"}],
        sourceIds=["official"],
        sourceType="official_verified",
    )

    forward = canonicalize_power_plants([first, second])["records"][0]
    backward = canonicalize_power_plants([deepcopy(second), deepcopy(first)])["records"][0]

    assert forward == backward
    assert forward["aliases"] == ["Alpha Energy Centre", "Alpha Plant", "Alpha Power Station"]
    assert [claim["id"] for claim in forward["evidence"]] == ["a", "z"]


def test_multi_fuel_and_most_specific_geography_survive_normalization() -> None:
    geographies = [
        {
            "type": "Feature",
            "id": "DE",
            "geometry": {"type": "Polygon", "coordinates": [[[5, 47], [16, 47], [16, 56], [5, 56], [5, 47]]]},
            "properties": {"id": "DE", "level": "country"},
        },
        {
            "type": "Feature",
            "id": "DE-HE",
            "geometry": {"type": "Polygon", "coordinates": [[[7, 48], [10, 48], [10, 52], [7, 52], [7, 48]]]},
            "properties": {"id": "DE-HE", "level": "admin_1"},
        },
        {
            "type": "Feature",
            "id": "DE71",
            "geometry": {"type": "Polygon", "coordinates": [[[8, 49], [9, 49], [9, 51], [8, 51], [8, 49]]]},
            "properties": {"id": "DE71", "level": "admin_2"},
        },
    ]
    record = power_record(
        country="DE",
        geographyId="DE",
        coordinates=[8.5, 50.0],
        primaryFuel="Natural gas",
        secondaryFuel="Oil",
        secondaryFuels=["Oil", "Biomass"],
    )

    normalized = canonicalize_power_plants([record], geographies=geographies)["records"][0]

    assert normalized["geographyId"] == "DE71"
    assert normalized["primaryFuel"] == "Natural gas"
    assert normalized["secondaryFuel"] == "Oil"
    assert normalized["secondaryFuels"] == ["Biomass", "Oil"]


def test_inactive_capacity_is_excluded_and_planned_capacity_is_separate() -> None:
    records = [
        power_record(id="operating", plantId="shared", unitId="operating", externalIds={"gemPlant": "G", "gemUnit": "U1"}),
        power_record(
            id="construction",
            plantId="shared",
            unitId="construction",
            externalIds={"gemPlant": "G", "gemUnit": "U2"},
            lifecycle="under_construction",
            capacityMw={"low": 45.0, "central": 50.0, "high": 55.0},
        ),
        power_record(
            id="announced",
            plantId="shared",
            unitId="announced",
            externalIds={"gemPlant": "G", "gemUnit": "U3"},
            technology="solar",
            primaryFuel="Solar",
            lifecycle="announced",
            capacityMw={"low": 20.0, "central": 25.0, "high": 30.0},
        ),
        power_record(id="paused", plantId="shared", unitId="paused", externalIds={"gemPlant": "G", "gemUnit": "U4"}, lifecycle="paused"),
        power_record(id="shelved", plantId="shared", unitId="shelved", externalIds={"gemPlant": "G", "gemUnit": "U5"}, lifecycle="shelved"),
        power_record(id="retired", plantId="shared", unitId="retired", externalIds={"gemPlant": "G", "gemUnit": "U6"}, lifecycle="retired"),
        power_record(id="cancelled", plantId="shared", unitId="cancelled", externalIds={"gemPlant": "G", "gemUnit": "U7"}, lifecycle="cancelled"),
    ]

    result = canonicalize_power_plants(records)
    plant = result["plants"][0]

    assert plant["unitCount"] == 7
    assert plant["operatingCapacityMw"]["central"] == 100.0
    assert plant["plannedCapacityMw"]["central"] == 75.0
    assert plant["plannedCapacityMwByTechnology"] == {"gas": 50.0, "solar": 25.0}
    by_id = {record["id"]: record for record in result["records"]}
    assert by_id["shelved"]["lifecycle"] == "paused"
    assert by_id["shelved"]["rawStatus"] == "shelved"
    assert by_id["retired"]["lifecycle"] == "cancelled"
    assert by_id["retired"]["rawStatus"] == "retired"


def test_normalized_active_records_fit_the_asset_contract() -> None:
    record = canonicalize_power_plants([power_record()])["records"][0]

    asset = AssetProperties.model_validate(record)

    assert asset.category == "power_generation"
    assert asset.source_type == "research_verified"


@pytest.mark.parametrize(
    "overrides",
    [
        {"capacityMw": {"low": 10.0, "central": float("nan"), "high": 20.0}},
        {"capacityMw": {"low": 10.0, "central": 15.0, "high": float("inf")}},
        {"coordinates": [float("inf"), 20.0]},
        {"coordinates": [10.0, float("nan")]},
    ],
)
def test_nonfinite_ranges_and_coordinates_are_rejected(overrides: dict) -> None:
    with pytest.raises(ValueError):
        canonicalize_power_plants([power_record(**overrides)])
