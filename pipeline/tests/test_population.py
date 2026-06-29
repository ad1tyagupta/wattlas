from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

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


def _artifact(
    *,
    years: tuple[int, ...] = (2026,),
    source_year: int | None = None,
) -> dict[str, object]:
    return build_population_artifact(
        boundaries_path=BOUNDARIES,
        raster_paths={year: RASTER for year in years},
        release_id="worldpop-global2-test-v1",
        source_id="worldpop-global2",
        source_years_by_target=(
            {year: source_year for year in years} if source_year is not None else None
        ),
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
    artifact = _artifact(years=TARGET_YEARS, source_year=2026)
    records = _records_by_key(artifact)

    assert {year for geography, year in records if geography == "AA-LEFT"} == set(TARGET_YEARS)
    row = records[("AA-LEFT", 2031)]
    assert row == {
        **row,
        "sourceRelease": "worldpop-global2-test-v1",
        "sourceYear": 2026,
        "baseYear": 2026,
        "valueKind": "estimated",
        "methodId": "worldpop-carry-forward-v1",
        "sourceIds": ["worldpop-global2"],
    }
    assert 0 < row["confidence"] <= 100
    assert row["confidence"] <= records[("AA-LEFT", 2026)]["confidence"]
    assert 0 < row["coverage"] <= 100
    assert artifact["sourceRelease"]["targetYears"] == list(TARGET_YEARS)
    assert artifact["sourceRelease"]["sourceYears"] == [2026]
    assert artifact["sourceRelease"]["targetSourceYears"] == {
        str(year): 2026 for year in TARGET_YEARS
    }
    assert artifact["sourceRelease"]["projectionMethodsByTarget"]["2031"] == (
        "worldpop-carry-forward-v1"
    )


def test_regions_without_defensible_raster_coverage_are_unavailable_not_zero() -> None:
    artifact = _artifact()
    records = _records_by_key(artifact)

    assert ("BB-OUTSIDE", 2026) not in records
    assert artifact["unavailable"] == [{
        "geographyId": "BB-OUTSIDE",
        "name": "Outside",
        "country": "BB",
        "year": 2026,
        "reason": "outside_raster_coverage",
    }]


def test_official_override_rescues_only_exact_unavailable_geography_and_year() -> None:
    artifact = _artifact(years=(2026, 2027), source_year=2026)

    overridden = apply_official_overrides(
        artifact,
        [{
            "geography_id": "BB-OUTSIDE",
            "country": "BB",
            "year": "2026",
            "population": "250",
            "source_id": "bb-statistics-office",
            "source_url": "https://statistics.example.test/bb/population",
            "release": "2026-r1",
            "method_id": "official-adm1-population",
            "confidence": "99",
            "coverage": "100",
        }],
    )
    records = _records_by_key(overridden)

    assert records[("BB-OUTSIDE", 2026)]["name"] == "Outside"
    assert records[("BB-OUTSIDE", 2026)]["valueKind"] == "reported"
    assert [(row["geographyId"], row["year"]) for row in overridden["unavailable"]] == [
        ("BB-OUTSIDE", 2027)
    ]


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


def test_single_raster_cli_defaults_to_earliest_target_as_disclosed_source_year(
    tmp_path: Path,
) -> None:
    output = tmp_path / "admin1-population.json"
    command = [
        sys.executable,
        "scripts/build-admin1-population.py",
        "--boundaries",
        str(BOUNDARIES),
        "--worldpop",
        str(RASTER),
        "--output",
        str(output),
    ]

    subprocess.run(command, check=True, capture_output=True, text=True)
    artifact = json.loads(output.read_text())
    records = _records_by_key(artifact)

    assert {row["sourceYear"] for row in records.values()} == {2026}
    assert records[("AA-LEFT", 2026)]["methodId"] == "worldpop-zonal-sum-v1"
    assert records[("AA-LEFT", 2027)]["methodId"] == "worldpop-carry-forward-v1"
    assert records[("AA-LEFT", 2031)]["baseYear"] == 2026
    assert artifact["sourceRelease"]["sourceYearResolution"] == {
        "method": "defaulted_to_earliest_target_year",
        "sourceYear": 2026,
    }


def test_single_raster_cli_honours_explicit_source_year(tmp_path: Path) -> None:
    output = tmp_path / "admin1-population.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/build-admin1-population.py",
            "--boundaries",
            str(BOUNDARIES),
            "--worldpop",
            str(RASTER),
            "--source-year",
            "2025",
            "--year",
            "2026",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    artifact = json.loads(output.read_text())
    row = _records_by_key(artifact)[("AA-LEFT", 2026)]
    assert row["sourceYear"] == 2025
    assert row["baseYear"] == 2025
    assert artifact["sourceRelease"]["sourceYearResolution"]["method"] == "explicit_cli"


def test_single_raster_cli_infers_a_unique_source_year_from_filename(tmp_path: Path) -> None:
    raster = tmp_path / "population_G2_R2025A_v1.tif"
    shutil.copyfile(RASTER, raster)
    output = tmp_path / "admin1-population.json"

    subprocess.run(
        [
            sys.executable,
            "scripts/build-admin1-population.py",
            "--boundaries",
            str(BOUNDARIES),
            "--worldpop",
            str(raster),
            "--year",
            "2026",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    artifact = json.loads(output.read_text())
    assert _records_by_key(artifact)[("AA-LEFT", 2026)]["sourceYear"] == 2025
    assert artifact["sourceRelease"]["sourceYearResolution"] == {
        "method": "inferred_from_filename",
        "sourceYear": 2025,
    }


def test_directory_cli_maps_distinct_year_files_to_exact_source_years(tmp_path: Path) -> None:
    raster_directory = tmp_path / "worldpop"
    raster_directory.mkdir()
    shutil.copyfile(RASTER, raster_directory / "population-2026.tif")
    shutil.copyfile(RASTER, raster_directory / "population-2027.tif")
    output = tmp_path / "admin1-population.json"

    subprocess.run(
        [
            sys.executable,
            "scripts/build-admin1-population.py",
            "--boundaries",
            str(BOUNDARIES),
            "--worldpop",
            str(raster_directory),
            "--year",
            "2026",
            "--year",
            "2027",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    artifact = json.loads(output.read_text())
    records = _records_by_key(artifact)
    assert records[("AA-LEFT", 2026)]["sourceYear"] == 2026
    assert records[("AA-LEFT", 2027)]["sourceYear"] == 2027
    assert records[("AA-LEFT", 2027)]["methodId"] == "worldpop-zonal-sum-v1"
    assert artifact["sourceRelease"]["sourceYears"] == [2026, 2027]
    assert artifact["sourceRelease"]["sourceYearResolution"] == {
        "method": "matched_distinct_target_year_files"
    }


def test_release_fingerprint_changes_when_target_to_source_mapping_changes() -> None:
    carried = _artifact(years=(2026, 2027), source_year=2026)
    per_year = _artifact(years=(2026, 2027))

    assert carried["sourceRelease"]["fingerprint"] != per_year["sourceRelease"]["fingerprint"]
    assert carried["sourceRelease"]["checksumsSha256"] == {
        "2026": sha256(RASTER.read_bytes()).hexdigest()
    }


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


def test_rebuild_check_is_sensitive_to_target_source_mapping(tmp_path: Path) -> None:
    path = tmp_path / "admin1-population.json"
    artifact = _artifact(years=(2026, 2027), source_year=2026)
    write_population_artifact(artifact, path)
    checksum = sha256(RASTER.read_bytes()).hexdigest()

    assert population_artifact_needs_rebuild(
        path,
        release_id="worldpop-global2-test-v1",
        checksums_by_year={2026: checksum},
        target_source_years={2026: 2026, 2027: 2026},
    ) is False
    assert population_artifact_needs_rebuild(
        path,
        release_id="worldpop-global2-test-v1",
        checksums_by_year={2026: checksum},
        target_source_years={2026: 2026, 2027: 2027},
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
