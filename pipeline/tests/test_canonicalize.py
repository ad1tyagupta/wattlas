import grid_scope.canonicalize as canonicalize
from grid_scope.canonicalize import assign_asset_country, assign_asset_geography, canonicalize_assets
from grid_scope.storage import RawCaptureStore


def asset(**overrides: object) -> dict:
    record = {
        "id": "source-a-campus",
        "name": "Example AI Campus",
        "operator": "Example Cloud",
        "geographyId": "US-LA",
        "country": "US",
        "category": "data_centre",
        "subtype": "ai_hpc",
        "lifecycle": "under_construction",
        "targetYear": 2028,
        "coordinates": [-91.7, 32.4],
        "locationPrecision": "region_centroid",
        "valueKind": "estimated",
        "sourceIds": ["source-a"],
        "externalIds": {"planning": "ABC-123"},
        "demandMw": {"low": 90, "central": 100, "high": 120},
    }
    record.update(overrides)
    return record


def test_exact_external_id_merges_announcements_and_preserves_sources() -> None:
    records = [
        asset(),
        asset(
            id="source-b-campus",
            name="Example Cloud Louisiana Campus",
            sourceIds=["source-b"],
            locationPrecision="exact",
            coordinates=[-91.71, 32.41],
        ),
    ]

    result = canonicalize_assets(records)

    assert len(result) == 1
    assert result[0]["sourceIds"] == ["source-a", "source-b"]
    assert result[0]["locationPrecision"] == "exact"
    assert result[0]["coordinates"] == [-91.71, 32.41]


def test_alias_and_close_capacity_can_merge_without_external_id() -> None:
    records = [
        asset(externalIds={}, name="AWS Saudi Region", operator="AWS", country="SA", geographyId="SA", coordinates=[46.67, 24.71]),
        asset(
            id="second",
            externalIds={},
            name="Amazon Web Services KSA Region",
            operator="Amazon Web Services",
            country="SA",
            geographyId="SA",
            coordinates=[46.68, 24.72],
            demandMw={"low": 92, "central": 105, "high": 125},
            sourceIds=["source-b"],
        ),
    ]

    result = canonicalize_assets(records, aliases={"aws": "amazon web services", "ksa": "saudi"})

    assert len(result) == 1


def test_nearby_but_materially_different_assets_remain_separate() -> None:
    records = [
        asset(externalIds={}),
        asset(
            id="different-campus",
            externalIds={},
            name="Different Campus",
            demandMw={"low": 450, "central": 500, "high": 600},
            sourceIds=["source-b"],
        ),
    ]

    assert len(canonicalize_assets(records)) == 2


def test_community_assets_without_operators_do_not_crash_or_merge() -> None:
    records = [
        asset(id="osm-node-1", externalIds={"osm": "node/1"}, operator=None, name="Mapped data centre · OSM 1"),
        asset(id="osm-node-2", externalIds={"osm": "node/2"}, operator=None, name="Mapped data centre · OSM 2"),
    ]

    assert len(canonicalize_assets(records)) == 2


def test_exact_point_is_spatially_assigned_to_most_specific_geography() -> None:
    geographies = [
        {
            "type": "Feature",
            "id": "AE",
            "geometry": {"type": "Polygon", "coordinates": [[[50, 20], [60, 20], [60, 30], [50, 30], [50, 20]]]},
            "properties": {"id": "AE", "level": "country"},
        },
        {
            "type": "Feature",
            "id": "AE-DU",
            "geometry": {"type": "Polygon", "coordinates": [[[54, 24], [56, 24], [56, 26], [54, 26], [54, 24]]]},
            "properties": {"id": "AE-DU", "level": "admin_1"},
        },
    ]
    record = asset(geographyId="AE", country="AE", coordinates=[55, 25], locationPrecision="exact")

    assert assign_asset_geography(record, geographies) == "AE-DU"


def test_country_only_announcement_does_not_gain_a_point() -> None:
    record = asset(coordinates=None, geographyId="CN", country="CN", locationPrecision="region_centroid")

    assert assign_asset_geography(record, []) == "CN"
    assert record["coordinates"] is None


def test_exact_point_is_assigned_to_un_country() -> None:
    countries = [{
        "type": "Feature",
        "id": "AE",
        "geometry": {"type": "Polygon", "coordinates": [[[50, 20], [60, 20], [60, 30], [50, 30], [50, 20]]]},
        "properties": {"id": "AE", "level": "country"},
    }]

    assert assign_asset_country(asset(coordinates=[55, 25], country="UNASSIGNED"), countries) == "AE"


def test_official_record_wins_when_merging_with_community_mapping() -> None:
    community = asset(
        id="osm-way-202",
        name="Example Campus",
        lifecycle="operational",
        demandMw=None,
        sourceType="community_mapped",
        sourceUrl="https://www.openstreetmap.org/way/202",
        sourceIds=["openstreetmap-infrastructure"],
        externalIds={"osm": "way/202", "planning": "ABC-123"},
    )
    official = asset(
        id="official-campus",
        name="Example AI Campus",
        lifecycle="under_construction",
        sourceType="official_verified",
        sourceUrl="https://example.com/project",
    )

    merged = canonicalize_assets([community, official])

    assert len(merged) == 1
    assert merged[0]["id"] == "official-campus"
    assert merged[0]["lifecycle"] == "under_construction"
    assert merged[0]["demandMw"]["central"] == 100
    assert merged[0]["sourceIds"] == ["openstreetmap-infrastructure", "source-a"]
    assert merged[0]["externalIds"] == {"osm": "way/202", "planning": "ABC-123"}


def test_equal_values_from_different_external_id_namespaces_do_not_merge() -> None:
    planning = asset(
        id="planning-record",
        externalIds={"planning": "12345"},
        name="North River Campus",
    )
    osm = asset(
        id="osm-record",
        externalIds={"osm": "12345"},
        name="South River Campus",
        operator="Different Operator",
        coordinates=[-80.0, 35.0],
    )

    assert len(canonicalize_assets([planning, osm])) == 2


def test_null_and_nonfinite_lineage_ids_are_filtered_not_stringified() -> None:
    record = asset(
        externalIds={
            "planning": None,
            "nan": float("nan"),
            "infinity": float("inf"),
            "osm": "way/42",
        },
        sourceIds=[None, float("nan"), float("inf"), "source-a"],
    )

    canonical = canonicalize_assets([record])[0]

    assert canonical["externalIds"] == {"osm": "way/42"}
    assert canonical["sourceIds"] == ["source-a"]
    assert "None" not in canonical["sourceIds"]


def test_equal_rank_asset_merge_is_input_order_independent_and_preserves_id_conflicts() -> None:
    first = asset(
        id="z-record",
        name="Zulu name",
        externalIds={"planning": "PLAN-1", "operator": "OP-A"},
        sourceIds=["z-source"],
    )
    second = asset(
        id="a-record",
        name="Alpha name",
        externalIds={"planning": "PLAN-1", "operator": "OP-B"},
        sourceIds=["a-source"],
    )

    forward = canonicalize_assets([first, second])[0]
    reverse = canonicalize_assets([second, first])[0]

    assert forward == reverse
    assert forward["externalIdAliases"]["operator"] == ["OP-A", "OP-B"]


def test_dense_generic_asset_block_avoids_all_pairs(
    monkeypatch,
) -> None:
    comparison_count = 0
    original = canonicalize._similar_asset

    def counted(first: dict, second: dict, aliases: dict[str, str]) -> bool:
        nonlocal comparison_count
        comparison_count += 1
        return original(first, second, aliases)

    monkeypatch.setattr(canonicalize, "_similar_asset", counted)
    records = [
        asset(
            id=f"solar-campus-{index}",
            name=f"Solar Compute Campus {index}",
            operator="Dense Operator",
            coordinates=[10.001 + (index % 10) * 0.0001, 20.001],
            externalIds={},
        )
        for index in range(2_000)
    ]

    result = canonicalize_assets(records)

    assert len(result) == 2_000
    assert comparison_count < 20_000


def test_geography_assignment_respects_polygon_holes() -> None:
    geographies = [
        {
            "type": "Feature",
            "id": "DONUT",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                    [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],
                ],
            },
            "properties": {"id": "DONUT", "level": "admin_1"},
        }
    ]

    assert assign_asset_geography(asset(geographyId="BASE", coordinates=[5, 5], locationPrecision="exact"), geographies) == "BASE"
    assert assign_asset_geography(asset(geographyId="BASE", coordinates=[2, 2], locationPrecision="exact"), geographies) == "DONUT"


def test_equal_depth_geography_overlap_uses_stable_parent_and_id_tie_break() -> None:
    first = {
        "type": "Feature",
        "id": "B",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
        "properties": {"id": "B", "parentId": "P", "level": "admin_1"},
    }
    second = {
        "type": "Feature",
        "id": "A",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
        "properties": {"id": "A", "parentId": "P", "level": "admin_1"},
    }
    record = asset(geographyId="BASE", coordinates=[1, 1], locationPrecision="exact")

    assert assign_asset_geography(record, [first, second]) == "A"
    assert assign_asset_geography(record, [second, first]) == "A"


def test_canonical_assets_round_trip_through_store(tmp_path) -> None:
    store = RawCaptureStore(tmp_path / "raw", tmp_path / "warehouse.duckdb")
    records = canonicalize_assets([asset()])

    store.save_canonical_assets(records)

    assert store.load_canonical_assets() == records
