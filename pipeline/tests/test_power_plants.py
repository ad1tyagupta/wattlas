from __future__ import annotations

from copy import deepcopy
import re

import pytest

import grid_scope.power_plants as power_plants
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


def test_canonical_record_id_uses_durable_anchor_and_preserves_source_id_aliases() -> None:
    gem = power_record(
        id="gem-source-row",
        externalIds={"gemPlant": "G-STABLE", "wikidata": "Q-STABLE"},
        owner="Original owner",
    )
    official = power_record(
        id="official-source-row",
        externalIds={"wikidata": "Q-STABLE", "official": "OFF-STABLE"},
        sourceType="official_verified",
        sourceIds=["official"],
        name="Corrected official name",
        coordinates=[-90.1, 35.1],
    )

    before = canonicalize_power_plants([gem])["records"][0]
    merged = canonicalize_power_plants([gem, official])["records"][0]
    gem["name"] = "Corrected GEM name"
    gem["plantName"] = "Corrected GEM plant name"
    gem["owner"] = "Corrected owner"
    gem["coordinates"] = [-90.2, 35.2]
    corrected = canonicalize_power_plants([official, gem])["records"][0]

    assert before["id"] == merged["id"] == corrected["id"]
    assert before["id"] == "wattlas-record-gemplant-g-stable"
    assert {"gem-source-row", "official-source-row"} <= set(merged["idAliases"])
    assert "wattlas-record-wikidata-q-stable" in merged["idAliases"]
    assert merged["idAliases"] == corrected["idAliases"]


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
        power_record(
            id="shelved",
            plantId="shared",
            unitId="shelved",
            externalIds={"gemPlant": "G", "gemUnit": "U5"},
            lifecycle="shelved",
            rawStatus="Shelved",
        ),
        power_record(
            id="retired",
            plantId="shared",
            unitId="retired",
            externalIds={"gemPlant": "G", "gemUnit": "U6"},
            lifecycle="retired",
            rawStatus="Retired",
        ),
        power_record(id="cancelled", plantId="shared", unitId="cancelled", externalIds={"gemPlant": "G", "gemUnit": "U7"}, lifecycle="cancelled"),
    ]

    result = canonicalize_power_plants(records)
    plant = result["plants"][0]

    assert plant["unitCount"] == 7
    assert plant["operatingCapacityMw"]["central"] == 100.0
    assert plant["plannedCapacityMw"]["central"] == 75.0
    assert plant["plannedCapacityMwByTechnology"] == {"gas": 50.0, "solar": 25.0}
    by_unit_id = {record["unitId"]: record for record in result["records"]}
    assert by_unit_id["shelved"]["lifecycle"] == "paused"
    assert by_unit_id["shelved"]["rawStatus"] == "Shelved"
    assert by_unit_id["retired"]["lifecycle"] == "cancelled"
    assert by_unit_id["retired"]["rawStatus"] == "Retired"


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


def test_null_and_nonfinite_power_lineage_ids_are_filtered() -> None:
    record = power_record(
        externalIds={
            "gemPlant": None,
            "Wiki Data": "Q42",
            "nan": float("nan"),
            "infinity": float("inf"),
        },
        sourceIds=[None, float("nan"), float("inf"), "gem-gipt"],
    )

    canonical = canonicalize_power_plants([record])["records"][0]

    assert canonical["externalIds"] == {"wikidata": "Q42"}
    assert canonical["sourceIds"] == ["gem-gipt"]


def test_dataset_country_aliases_merge_iso3_and_country_name() -> None:
    gem = power_record(
        id="gem-denmark",
        country="Denmark",
        countryIso3=None,
        externalIds={},
        plantId="gem-denmark",
    )
    wri = power_record(
        id="wri-denmark",
        country="Denmark",
        countryIso3="DNK",
        externalIds={},
        plantId="wri-denmark",
        sourceIds=["wri-gppd"],
    )

    result = canonicalize_power_plants([gem, wri])

    assert len(result["records"]) == 1
    assert result["records"][0]["canonicalCountryKey"] == "DNK"


def test_adm1_names_cannot_be_mistaken_for_country_iso3_codes() -> None:
    goa = {
        "type": "Feature",
        "id": "IN-GOA",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[70, 10], [71, 10], [71, 11], [70, 11], [70, 10]]],
        },
        "properties": {
            "id": "IN-GOA",
            "name": "Goa",
            "country": "IN",
            "level": "admin_1",
        },
    }
    record = power_record(
        id="india-record",
        country="IN",
        countryIso3=None,
        coordinates=[77, 20],
        externalIds={},
        plantId="india-record",
    )

    canonical = canonicalize_power_plants([record], geographies=[goa])["records"][0]

    assert canonical["canonicalCountryKey"] == "IN"


def test_spatial_country_backfill_reconciles_gem_wri_and_osm_country_forms() -> None:
    geographies = [
        {
            "type": "Feature",
            "id": "US",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-110, 25], [-80, 25], [-80, 45], [-110, 45], [-110, 25]]],
            },
            "properties": {
                "id": "US",
                "name": "United States",
                "country": "US",
                "iso3": "USA",
                "level": "country",
            },
        },
        {
            "type": "Feature",
            "id": "US-TX",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-101, 29], [-99, 29], [-99, 31], [-101, 31], [-101, 29]]],
            },
            "properties": {
                "id": "US-TX",
                "name": "Texas",
                "country": "US",
                "parentId": "US",
                "level": "admin_1",
            },
        },
    ]
    gem = power_record(
        id="gem-us",
        externalIds={},
        plantId="gem-us",
        country="United States",
        countryIso3=None,
        name="Lone Star Solar Plant",
        plantName="Lone Star Solar Plant",
        operator="Shared Operator",
        coordinates=[-100.0, 30.0],
    )
    wri = power_record(
        id="wri-us",
        externalIds={},
        plantId="wri-us",
        country="United States of America",
        countryIso3="USA",
        name="Lone Star Solar Station",
        plantName="Lone Star Solar Station",
        operator="Shared Operator",
        coordinates=[-100.001, 30.001],
    )
    osm = power_record(
        id="osm-us",
        externalIds={},
        plantId="osm-us",
        country=None,
        countryIso3=None,
        geographyId="UNASSIGNED",
        name="Lone Star Solar Project",
        plantName="Lone Star Solar Project",
        operator="Shared Operator",
        coordinates=[-100.002, 30.002],
        sourceType="community_mapped",
        sourceIds=["osm-power"],
    )

    result = canonicalize_power_plants([osm, wri, gem], geographies=geographies)

    assert len(result["records"]) == 1
    record = result["records"][0]
    assert record["country"] == "US"
    assert record["canonicalCountryKey"] == "USA"
    assert record["geographyId"] == "US-TX"


def test_location_tuple_is_selected_atomically_with_precision_before_source_rank() -> None:
    official = power_record(
        id="official-location",
        externalIds={"wikidata": "Q-LOCATION"},
        coordinates=[-95.0, 31.0],
        locationPrecision="region_centroid",
        geographyId="US-OFFICIAL-REGION",
        sourceType="official_verified",
        sourceIds=["official"],
    )
    osm = power_record(
        id="osm-location",
        externalIds={"wikidata": "Q-LOCATION", "osm": "way/1"},
        coordinates=[-96.8, 32.8],
        locationPrecision="exact",
        geographyId="US-TX",
        sourceType="community_mapped",
        sourceIds=["osm-power"],
    )

    result = canonicalize_power_plants([official, osm])
    record = result["records"][0]

    assert record["coordinates"] == [-96.8, 32.8]
    assert record["locationPrecision"] == "exact"
    assert record["geographyId"] == "US-TX"
    for field in ("coordinates", "locationPrecision", "geographyId", "canonicalCountryKey"):
        assert record["fieldProvenance"][field]["sourceIds"] == ["osm-power"]
    assert result["plants"][0]["coordinates"] == [-96.8, 32.8]
    assert result["plants"][0]["locationPrecision"] == "exact"
    assert result["plants"][0]["geographyId"] == "US-TX"


def test_distinct_twin_units_never_fuzzy_merge_on_plant_fields() -> None:
    gem_unit = power_record(
        id="gem-twin-1",
        name="Twin Unit 1",
        plantName="Twin Station",
        unitId="gem-unit-1",
        externalIds={"gemPlant": "G-TWIN", "gemUnit": "G-U1"},
    )
    official_unit = power_record(
        id="official-twin-2",
        name="Twin Unit 2",
        plantName="Twin Station",
        unitId="official-unit-2",
        externalIds={"gemPlant": "G-TWIN", "officialUnit": "O-U2"},
        sourceType="official_verified",
        sourceIds=["official"],
    )

    result = canonicalize_power_plants([gem_unit, official_unit])

    assert len(result["units"]) == 2
    assert result["plants"][0]["unitCount"] == 2


def test_transitive_external_identity_bridge_cannot_merge_conflicting_clusters() -> None:
    q1 = power_record(
        id="a-q1",
        externalIds={"wikidata": "Q1"},
        name="Q1 Plant",
        plantName="Q1 Plant",
    )
    bridge = power_record(
        id="b-bridge",
        externalIds={"wikidata": "Q1", "official": "X"},
        name="Bridge Plant",
        plantName="Bridge Plant",
    )
    q2 = power_record(
        id="c-q2",
        externalIds={"wikidata": "Q2", "official": "X"},
        name="Q2 Plant",
        plantName="Q2 Plant",
    )

    result = canonicalize_power_plants([q2, bridge, q1])

    assert len(result["records"]) == 2
    assert sorted(
        tuple(record.get("externalIdAliases", {}).get("wikidata", [record["externalIds"].get("wikidata")]))
        for record in result["records"]
    ) == [("Q1",), ("Q2",)]


def test_summary_ids_are_unique_permutation_stable_and_source_rank_independent() -> None:
    base = power_record(
        id="gem-alpha",
        externalIds={"wikidata": "Q100", "gemPlant": "G100"},
        plantId="gem-alpha",
    )
    stronger = power_record(
        id="official-alpha",
        externalIds={"WikiData": "Q100", "official": "OFF100"},
        plantId="official-alpha",
        sourceType="official_verified",
        sourceIds=["official"],
    )
    duplicate_source_id_a = power_record(
        id="source-plant-a",
        name="Plant A",
        plantName="Plant A",
        operator="A Operator",
        coordinates=[1, 1],
        externalIds={},
        plantId=None,
    )
    duplicate_source_id_b = power_record(
        id="source-plant-b",
        name="Plant B",
        plantName="Plant B",
        operator="B Operator",
        coordinates=[20, 20],
        externalIds={},
        plantId=None,
    )

    base_id = canonicalize_power_plants([base])["plants"][0]["id"]
    with_stronger = canonicalize_power_plants([stronger, base])["plants"][0]["id"]
    forward = canonicalize_power_plants([base, duplicate_source_id_a, duplicate_source_id_b])
    reverse = canonicalize_power_plants([duplicate_source_id_b, duplicate_source_id_a, base])

    assert base_id == with_stronger
    assert [plant["id"] for plant in forward["plants"]] == [plant["id"] for plant in reverse["plants"]]
    assert len({plant["id"] for plant in forward["plants"]}) == 3
    assert all(plant["id"].startswith("wattlas-plant-") for plant in forward["plants"])
    assert len({record["id"] for record in forward["records"]}) == 3
    assert [record["id"] for record in forward["records"]] == [
        record["id"] for record in reverse["records"]
    ]


def test_ambiguous_duplicate_source_ids_without_durable_identity_are_rejected() -> None:
    first = power_record(
        id="ambiguous-source-id",
        externalIds={},
        plantId=None,
        unitId=None,
        name="Ambiguous Alpha",
        plantName="Ambiguous Alpha",
        coordinates=[1, 1],
    )
    second = power_record(
        id="ambiguous-source-id",
        externalIds={},
        plantId=None,
        unitId=None,
        name="Ambiguous Beta",
        plantName="Ambiguous Beta",
        coordinates=[20, 20],
    )

    with pytest.raises(ValueError, match="ambiguous duplicate canonical record ID"):
        canonicalize_power_plants([first, second])


def test_conflicting_clusters_with_same_full_anchor_and_no_relationship_are_rejected() -> None:
    first = power_record(
        id="conflict-a",
        externalIds={"wikidata": "Q-SAME", "official": "OFF-A"},
        plantId=None,
        unitId=None,
    )
    second = power_record(
        id="conflict-b",
        externalIds={"wikidata": "Q-SAME", "official": "OFF-B"},
        plantId=None,
        unitId=None,
    )

    with pytest.raises(ValueError, match="ambiguous duplicate canonical record ID"):
        canonicalize_power_plants([first, second])


def test_summary_id_aliases_preserve_previous_gem_anchor_when_wikidata_arrives() -> None:
    gem = power_record(
        id="gem-continuity",
        externalIds={"gemPlant": "G-CONTINUITY"},
        plantId="gem-continuity",
    )
    wikidata = power_record(
        id="official-continuity",
        externalIds={"gemPlant": "G-CONTINUITY", "wikidata": "Q-CONTINUITY"},
        plantId="official-continuity",
        sourceType="official_verified",
        sourceIds=["official"],
    )

    old_id = canonicalize_power_plants([gem])["plants"][0]["id"]
    upgraded = canonicalize_power_plants([gem, wikidata])["plants"][0]

    assert upgraded["id"] == "wattlas-plant-wikidata-q-continuity"
    assert old_id in upgraded["idAliases"]
    assert upgraded["id"] not in upgraded["idAliases"]
    assert len(upgraded["idAliases"]) == len(set(upgraded["idAliases"]))


def test_collision_suffixes_ignore_mutable_owner_metadata() -> None:
    common_prefix = "Q" + "A" * 80
    first = power_record(
        id="duplicate-source-id",
        externalIds={"wikidata": f"{common_prefix}1"},
        plantId="collision-a",
        name="Collision Alpha",
        plantName="Collision Alpha",
        coordinates=[1, 1],
        owner="Owner version one",
    )
    second = power_record(
        id="duplicate-source-id",
        externalIds={"wikidata": f"{common_prefix}2"},
        plantId="collision-b",
        name="Collision Beta",
        plantName="Collision Beta",
        coordinates=[20, 20],
        owner="Other owner",
    )

    before_result = canonicalize_power_plants([first, second])
    before = before_result["plants"]
    stronger = power_record(
        id="stronger-source-row",
        externalIds={
            "wikidata": f"{common_prefix}1",
            "official": "OFF-COLLISION-A",
        },
        plantId="collision-a",
        name="Stronger corrected name",
        coordinates=[2, 2],
        sourceType="official_verified",
        sourceIds=["official"],
    )
    first["owner"] = "Owner version two"
    first["updatedAt"] = "2030-01-01"
    owner_result = canonicalize_power_plants([second, first])
    assert [plant["id"] for plant in before] == [
        plant["id"] for plant in owner_result["plants"]
    ]
    first["name"] = "Corrected source name"
    first["plantName"] = "Corrected source plant name"
    first["coordinates"] = [3, 3]
    metadata_result = canonicalize_power_plants([second, first])
    stronger_result = canonicalize_power_plants([stronger, second, first])

    assert [plant.get("idAliases", []) for plant in before] == [
        plant.get("idAliases", []) for plant in owner_result["plants"]
    ]
    assert len({plant["id"] for plant in before}) == 2
    assert all(len(plant.get("idAliases", [])) == len(set(plant.get("idAliases", []))) for plant in before)
    all_aliases = [alias for plant in before for alias in plant.get("idAliases", [])]
    assert len(all_aliases) == len(set(all_aliases))
    assert not set(all_aliases) & {plant["id"] for plant in before}
    record_aliases = [
        alias
        for record in before_result["records"]
        for alias in record.get("idAliases", [])
    ]
    unsuffixed_record_id = (
        "wattlas-record-wikidata-"
        + re.sub(r"[^a-z0-9]+", "-", f"{common_prefix}1".casefold()).strip("-")[:64]
    )
    assert record_aliases.count(unsuffixed_record_id) == 1
    before_record_ids = sorted(record["id"] for record in before_result["records"])
    after_record_ids = sorted(record["id"] for record in stronger_result["records"])
    assert before_record_ids == after_record_ids
    for result in (before_result, owner_result, metadata_result, stronger_result):
        primary_ids = {record["id"] for record in result["records"]}
        aliases = [
            alias
            for record in result["records"]
            for alias in record.get("idAliases", [])
        ]
        assert len(aliases) == len(set(aliases))
        assert not primary_ids & set(aliases)
    assert canonicalize_power_plants([first, second, stronger])["records"] == stronger_result[
        "records"
    ]


def test_incomplete_units_use_compatible_aggregate_capacity_fallback() -> None:
    missing_unit = power_record(
        id="gem-unit-missing",
        name="Alpha Unit 1",
        unitId="gem-unit-missing",
        externalIds={"gemPlant": "G-ALPHA", "gemUnit": "U-MISSING"},
        capacityMw=None,
        capacityValueKind="unavailable",
    )
    aggregate = power_record(
        id="wri-alpha-aggregate",
        unitId=None,
        externalIds={"gemPlant": "G-ALPHA", "wri": "W-ALPHA"},
        capacityMw={"low": 100, "central": 100, "high": 100},
    )

    plant = canonicalize_power_plants([missing_unit, aggregate])["plants"][0]

    assert plant["operatingCapacityMw"] == {"low": 100.0, "central": 100.0, "high": 100.0}
    assert plant["operatingCapacityCoverage"]["method"] == "aggregate_fallback"
    assert plant["operatingCapacityCoverage"]["knownUnitCount"] == 0
    assert plant["operatingCapacityCoverage"]["totalUnitCount"] == 1


def test_reported_aggregate_outranks_complete_estimated_unit_sum() -> None:
    units = [
        power_record(
            id=f"modelled-unit-{index}",
            unitId=f"modelled-unit-{index}",
            externalIds={"gemPlant": "G-QUALITY", "gemUnit": f"U-{index}"},
            capacityMw={"low": 40, "central": 40, "high": 40},
            capacityValueKind="estimated",
            valueKind="estimated",
            sourceType="modelled",
            sourceIds=["modelled-units"],
        )
        for index in range(2)
    ]
    aggregate = power_record(
        id="official-aggregate",
        unitId=None,
        externalIds={"gemPlant": "G-QUALITY", "official": "OFF-QUALITY"},
        capacityMw={"low": 100, "central": 100, "high": 100},
        capacityValueKind="reported",
        valueKind="reported",
        sourceType="official_verified",
        sourceIds=["official-capacity"],
    )

    plant = canonicalize_power_plants([*units, aggregate])["plants"][0]

    assert plant["operatingCapacityMw"]["central"] == 100
    assert plant["operatingCapacityCoverage"]["method"] == "aggregate_preferred"
    assert plant["operatingCapacityCoverage"]["provenance"]["valueKind"] == "reported"
    assert plant["operatingCapacityCoverage"]["provenance"]["sourceIds"] == [
        "official-capacity"
    ]


def test_complete_reported_unit_sum_outranks_estimated_aggregate() -> None:
    units = [
        power_record(
            id=f"reported-unit-{index}",
            unitId=f"reported-unit-{index}",
            externalIds={"gemPlant": "G-QUALITY-2", "gemUnit": f"RU-{index}"},
            capacityMw={"low": 50, "central": 50, "high": 50},
            capacityValueKind="reported",
            valueKind="reported",
            sourceType="research_verified",
            sourceIds=["reported-units"],
        )
        for index in range(2)
    ]
    aggregate = power_record(
        id="official-estimate",
        unitId=None,
        externalIds={"gemPlant": "G-QUALITY-2", "official": "OFF-ESTIMATE"},
        capacityMw={"low": 120, "central": 120, "high": 120},
        capacityValueKind="estimated",
        valueKind="estimated",
        sourceType="official_verified",
        sourceIds=["official-estimate"],
    )

    plant = canonicalize_power_plants([aggregate, *units])["plants"][0]

    assert plant["operatingCapacityMw"]["central"] == 100
    assert plant["operatingCapacityCoverage"]["method"] == "complete_unit_sum"
    assert plant["operatingCapacityCoverage"]["provenance"]["valueKind"] == "reported"
    assert plant["operatingCapacityCoverage"]["provenance"]["sourceIds"] == [
        "reported-units"
    ]


def test_capacity_metric_kind_and_provenance_are_selected_atomically() -> None:
    reported = power_record(
        id="community-reported",
        externalIds={"wikidata": "Q500"},
        sourceType="community_mapped",
        sourceIds=["community"],
        capacityMw={"low": 80, "central": 90, "high": 100},
        capacityValueKind="reported",
    )
    estimated = power_record(
        id="official-estimated",
        externalIds={"wikidata": "Q500"},
        sourceType="official_verified",
        sourceIds=["official"],
        capacityMw={"low": 95, "central": 100, "high": 105},
        capacityValueKind="estimated",
    )

    record = canonicalize_power_plants([reported, estimated])["records"][0]

    assert record["capacityValueKind"] == "reported"
    assert record["fieldProvenance"]["capacityValueKind"] == record["fieldProvenance"]["capacityMw"]
    assert record["fieldProvenance"]["capacityMw"]["sourceIds"] == ["community"]


def test_capacity_rollup_uses_selected_field_provenance_not_merged_row_lineage() -> None:
    community_aggregate = power_record(
        id="community-aggregate",
        unitId=None,
        externalIds={"gemPlant": "G-FIELD", "wikidata": "Q-FIELD"},
        capacityMw={"low": 100, "central": 100, "high": 100},
        capacityValueKind="reported",
        valueKind="reported",
        sourceType="community_mapped",
        sourceIds=["community-capacity"],
    )
    official_aggregate = power_record(
        id="official-aggregate-field",
        unitId=None,
        externalIds={"gemPlant": "G-FIELD", "wikidata": "Q-FIELD"},
        capacityMw={"low": 110, "central": 110, "high": 110},
        capacityValueKind="estimated",
        valueKind="estimated",
        sourceType="official_verified",
        sourceIds=["official-registry"],
        name="Official registry name",
    )

    aggregate_only = canonicalize_power_plants(
        [official_aggregate, community_aggregate]
    )
    aggregate_record = aggregate_only["records"][0]
    aggregate_provenance = aggregate_only["plants"][0]["operatingCapacityCoverage"][
        "provenance"
    ]

    assert aggregate_record["sourceType"] == "official_verified"
    assert aggregate_record["sourceIds"] == ["community-capacity", "official-registry"]
    assert aggregate_record["fieldProvenance"]["capacityMw"] == {
        "sourceType": "community_mapped",
        "sourceIds": ["community-capacity"],
        "valueKind": "reported",
    }
    assert aggregate_provenance["valueKind"] == "reported"
    assert aggregate_provenance["sourceTypes"] == ["community_mapped"]
    assert aggregate_provenance["sourceIds"] == ["community-capacity"]

    units = [
        power_record(
            id=f"research-unit-{index}",
            unitId=f"research-unit-{index}",
            externalIds={"gemPlant": "G-FIELD", "gemUnit": f"FIELD-U-{index}"},
            capacityMw={"low": 40, "central": 40, "high": 40},
            capacityValueKind="reported",
            valueKind="reported",
            sourceType="research_verified",
            sourceIds=["research-units"],
        )
        for index in range(2)
    ]
    with_units = canonicalize_power_plants(
        [official_aggregate, community_aggregate, *units]
    )["plants"][0]

    assert with_units["operatingCapacityMw"]["central"] == 80
    assert with_units["operatingCapacityCoverage"]["method"] == "complete_unit_sum"
    assert with_units["operatingCapacityCoverage"]["provenance"]["sourceIds"] == [
        "research-units"
    ]


def test_fuzzy_comparisons_are_blocked_below_quadratic_growth(monkeypatch: pytest.MonkeyPatch) -> None:
    comparison_count = 0
    original = power_plants._strong_fuzzy_duplicate

    def counted(first: dict, second: dict, aliases: dict[str, str]) -> bool:
        nonlocal comparison_count
        comparison_count += 1
        return original(first, second, aliases)

    monkeypatch.setattr(power_plants, "_strong_fuzzy_duplicate", counted)
    records = [
        power_record(
            id=f"synthetic-{index}",
            name=f"Synthetic Plant {index}",
            plantName=f"Synthetic Plant {index}",
            operator=f"Operator {index}",
            coordinates=[-170 + (index % 340), -70 + (index % 140)],
            externalIds={},
            plantId=f"synthetic-{index}",
        )
        for index in range(3_000)
    ]

    result = canonicalize_power_plants(records)

    assert len(result["records"]) == 3_000
    assert comparison_count < 30_000


def test_dense_common_token_block_uses_compound_name_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    comparison_count = 0
    plant_comparison_count = 0
    original_record = power_plants._strong_fuzzy_duplicate
    original_plant = power_plants._same_plant

    def counted_record(first: dict, second: dict, aliases: dict[str, str]) -> bool:
        nonlocal comparison_count
        comparison_count += 1
        return original_record(first, second, aliases)

    def counted_plant(first: dict, second: dict, aliases: dict[str, str]) -> bool:
        nonlocal plant_comparison_count
        plant_comparison_count += 1
        return original_plant(first, second, aliases)

    monkeypatch.setattr(power_plants, "_strong_fuzzy_duplicate", counted_record)
    monkeypatch.setattr(power_plants, "_same_plant", counted_plant)
    records = [
        power_record(
            id=f"dense-solar-{index}",
            name=f"Solar Ridge {index}",
            plantName=f"Solar Ridge {index}",
            operator="Dense Solar Operator",
            coordinates=[10.001 + (index % 10) * 0.0001, 20.001],
            externalIds={},
            plantId=f"dense-solar-{index}",
        )
        for index in range(2_000)
    ]

    result = canonicalize_power_plants(records)

    assert len(result["records"]) == len(result["plants"]) == 2_000
    assert comparison_count + plant_comparison_count < 20_000


def test_large_shared_plant_does_not_compare_every_distinct_unit_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    comparison_count = 0
    original = power_plants._strong_fuzzy_duplicate

    def counted(first: dict, second: dict, aliases: dict[str, str]) -> bool:
        nonlocal comparison_count
        comparison_count += 1
        return original(first, second, aliases)

    monkeypatch.setattr(power_plants, "_strong_fuzzy_duplicate", counted)
    records = [
        power_record(
            id=f"gem-unit-{index}",
            unitId=f"gem-unit-{index}",
            name=f"Alpha Unit {index}",
            externalIds={"gemPlant": "GEM-MEGA", "gemUnit": f"GEM-U-{index}"},
        )
        for index in range(3_000)
    ]

    result = canonicalize_power_plants(records)

    assert len(result["units"]) == 3_000
    assert len(result["plants"]) == 1
    assert comparison_count < 30_000
