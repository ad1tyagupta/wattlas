from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from grid_scope.connectors.worldpop import WorldPopConnector
from grid_scope.models import ConnectorState
from grid_scope.population import (
    TARGET_YEARS,
    apply_official_overrides,
    build_population_artifact,
    load_population_artifact,
    population_artifact_needs_rebuild,
    reconcile_country_totals,
    write_population_artifact,
)


FIXTURES = Path(__file__).parent / "fixtures"
BOUNDARIES = FIXTURES / "admin1-small.geojson"
RASTER = FIXTURES / "worldpop-tiny.tif"


def _artifact(*, years: tuple[int, ...] = (2026,)) -> dict[str, object]:
    return build_population_artifact(
        boundaries_path=BOUNDARIES,
        raster_paths={year: RASTER for year in years},
        release_id="worldpop-global2-test-v1",
        source_id="worldpop-global2",
    )


def _records_by_key(artifact: dict[str, object]) -> dict[tuple[str, int], dict[str, object]]:
    records = artifact["records"]
    assert isinstance(records, list)
    return {(str(row["geographyId"]), int(row["year"])): row for row in records}


def test_zonal_population_excludes_nodata_and_respects_exact_multipolygon_mask() -> None:
    records = _records_by_key(_artifact())

    # The raster's left cells are 10, nodata, 1, 2. Nodata is not population.
    assert records[("AA-LEFT", 2026)]["population"] == 13
    # The exact MultiPolygon includes the 30, 3 and 4 cells; its hole excludes 40.
    assert records[("AA-RIGHT", 2026)]["population"] == 37
    assert all(isinstance(row["population"], int) and row["population"] >= 0 for row in records.values())
    assert records[("AA-LEFT", 2026)]["roundingMethod"] == "round-half-up"


def test_modelled_rows_keep_complete_worldpop_lineage_for_2026_to_2031() -> None:
    artifact = _artifact(years=TARGET_YEARS)
    records = _records_by_key(artifact)

    assert {year for geography, year in records if geography == "AA-LEFT"} == set(TARGET_YEARS)
    row = records[("AA-LEFT", 2031)]
    assert row == {
        **row,
        "sourceRelease": "worldpop-global2-test-v1",
        "sourceYear": 2031,
        "valueKind": "estimated",
        "methodId": "worldpop-zonal-sum-v1",
        "sourceIds": ["worldpop-global2"],
    }
    assert 0 < row["confidence"] <= 100
    assert 0 < row["coverage"] <= 100


def test_regions_without_defensible_raster_coverage_are_unavailable_not_zero() -> None:
    artifact = _artifact()
    records = _records_by_key(artifact)

    assert ("BB-OUTSIDE", 2026) not in records
    assert artifact["unavailable"] == [{
        "geographyId": "BB-OUTSIDE",
        "country": "BB",
        "year": 2026,
        "reason": "outside_raster_coverage",
    }]


def test_official_override_replaces_only_exact_geography_and_year() -> None:
    artifact = _artifact(years=(2026, 2027))
    overridden = apply_official_overrides(
        artifact,
        [{
            "geography_id": "AA-LEFT",
            "country": "AA",
            "year": "2026",
            "population": "99",
            "source_id": "aa-statistics-office",
            "source_url": "https://statistics.example.test/population",
            "release": "2026-r1",
            "method_id": "official-adm1-population",
            "confidence": "98",
            "coverage": "100",
        }],
    )
    records = _records_by_key(overridden)

    assert records[("AA-LEFT", 2026)]["population"] == 99
    assert records[("AA-LEFT", 2026)]["valueKind"] == "reported"
    assert records[("AA-LEFT", 2026)]["sourceIds"] == ["aa-statistics-office"]
    assert records[("AA-LEFT", 2027)]["population"] == 13
    assert records[("AA-RIGHT", 2026)]["population"] == 37


def test_unmatched_override_does_not_invent_region_or_year() -> None:
    artifact = _artifact()
    original = json.dumps(artifact, sort_keys=True)

    result = apply_official_overrides(artifact, [{
        "geography_id": "AA-MISSING",
        "country": "AA",
        "year": "2028",
        "population": "500",
        "source_id": "aa-statistics-office",
        "source_url": "https://statistics.example.test/population",
        "release": "2028-r1",
        "method_id": "official-adm1-population",
        "confidence": "100",
        "coverage": "100",
    }])

    assert json.dumps(result, sort_keys=True) == original


def test_country_reconciliation_preserves_shares_and_records_factor() -> None:
    artifact = _artifact()
    result = reconcile_country_totals(
        artifact,
        {("AA", 2026): {"population": 100, "sourceId": "worldpop-country-control"}},
        tolerance=0.001,
    )
    records = _records_by_key(result)

    assert sum(int(row["population"]) for (geography, _), row in records.items() if geography.startswith("AA-")) == 100
    assert records[("AA-LEFT", 2026)]["population"] == 26
    assert records[("AA-RIGHT", 2026)]["population"] == 74
    assert records[("AA-LEFT", 2026)]["adjustmentFactor"] == pytest.approx(2.0)
    assert records[("AA-LEFT", 2026)]["controlSourceId"] == "worldpop-country-control"


def test_country_reconciliation_within_tolerance_leaves_values_unadjusted() -> None:
    artifact = _artifact()
    result = reconcile_country_totals(
        artifact,
        {("AA", 2026): {"population": 51, "sourceId": "worldpop-country-control"}},
        tolerance=0.03,
    )
    records = _records_by_key(result)

    assert records[("AA-LEFT", 2026)]["population"] == 13
    assert records[("AA-LEFT", 2026)]["adjustmentFactor"] == 1.0


def test_country_reconciliation_keeps_official_regions_fixed_and_scales_modelled_residual() -> None:
    artifact = apply_official_overrides(
        _artifact(),
        [{
            "geography_id": "AA-LEFT",
            "country": "AA",
            "year": "2026",
            "population": "40",
            "source_id": "aa-statistics-office",
            "source_url": "https://statistics.example.test/population",
            "release": "2026-r1",
            "method_id": "official-adm1-population",
            "confidence": "98",
            "coverage": "100",
        }],
    )

    result = reconcile_country_totals(
        artifact,
        {("AA", 2026): {"population": 100, "sourceId": "worldpop-country-control"}},
        tolerance=0,
    )
    records = _records_by_key(result)

    assert records[("AA-LEFT", 2026)]["population"] == 40
    assert records[("AA-LEFT", 2026)]["valueKind"] == "reported"
    assert records[("AA-LEFT", 2026)]["adjustmentFactor"] == 1.0
    assert records[("AA-RIGHT", 2026)]["population"] == 60
    assert sum(row["population"] for row in records.values()) == 100


def test_compact_artifact_is_deterministic_and_fingerprinted(tmp_path: Path) -> None:
    artifact = _artifact()
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    write_population_artifact(artifact, first)
    write_population_artifact(artifact, second)

    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text())
    expected_checksum = sha256(RASTER.read_bytes()).hexdigest()
    assert payload["sourceRelease"]["checksumsSha256"] == {"2026": expected_checksum}
    assert payload["sourceRelease"]["fingerprint"].startswith("sha256:")
    assert "geometry" not in first.read_text()


def test_daily_loader_needs_no_raster_and_rebuilds_only_for_upstream_change(tmp_path: Path) -> None:
    path = tmp_path / "admin1-population.json"
    artifact = _artifact()
    write_population_artifact(artifact, path)
    checksum = sha256(RASTER.read_bytes()).hexdigest()

    loaded = load_population_artifact(path)

    assert loaded["records"][0]["geographyId"] == "AA-LEFT"
    assert population_artifact_needs_rebuild(
        path,
        release_id="worldpop-global2-test-v1",
        checksums_by_year={2026: checksum},
    ) is False
    assert population_artifact_needs_rebuild(
        path,
        release_id="worldpop-global2-test-v2",
        checksums_by_year={2026: checksum},
    ) is True
    assert population_artifact_needs_rebuild(
        path,
        release_id="worldpop-global2-test-v1",
        checksums_by_year={2026: "changed"},
    ) is True


def test_worldpop_connector_reports_not_configured_without_path_or_url() -> None:
    result = WorldPopConnector(path=None, url=None, release_id="global2-2026").resolve()

    assert result.state == ConnectorState.NOT_CONFIGURED
    assert result.release is None


def test_worldpop_connector_streams_checksum_for_local_release() -> None:
    result = WorldPopConnector(
        path=RASTER,
        url=None,
        release_id="global2-test-v1",
        source_year=2026,
    ).resolve()

    assert result.state == ConnectorState.CURRENT
    assert result.release is not None
    assert result.release.checksum_sha256 == sha256(RASTER.read_bytes()).hexdigest()
    assert result.release.source_year == 2026


def test_population_builder_reprojects_an_explicit_mismatched_crs(tmp_path: Path) -> None:
    no_crs = json.loads(BOUNDARIES.read_text())
    no_crs["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    path = tmp_path / "boundaries.geojson"
    path.write_text(json.dumps(no_crs))

    # An explicit CRS is accepted and reprojected rather than silently treated as WGS84.
    artifact = build_population_artifact(
        boundaries_path=path,
        raster_paths={2026: RASTER},
        release_id="worldpop-global2-test-v1",
        source_id="worldpop-global2",
    )
    assert artifact["unavailable"]
