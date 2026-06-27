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


def test_canonical_assets_round_trip_through_store(tmp_path) -> None:
    store = RawCaptureStore(tmp_path / "raw", tmp_path / "warehouse.duckdb")
    records = canonicalize_assets([asset()])

    store.save_canonical_assets(records)

    assert store.load_canonical_assets() == records
