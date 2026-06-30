from datetime import UTC, datetime
import json

import pytest
from pathlib import Path

from grid_scope.cli import (
    POWER_SOURCE_PRECEDENCE,
    REFRESH_STEPS,
    build_connector_status,
    build_regional_energy_model,
    collect_power_source_records,
    load_refresh_model_artifacts,
    main,
    merge_asset_feeds,
    validate_refresh_quality,
    _optional_network_result,
)
from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState
from grid_scope.storage import RawCaptureStore
from grid_scope.power_balance import load_generation_assumptions
from grid_scope.regional_demand import load_regional_demand_methods


def test_cli_help_exits_cleanly(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "daily snapshot" in capsys.readouterr().out.lower()


def test_cli_describes_wattlas() -> None:
    parser = __import__("grid_scope.cli", fromlist=["build_parser"]).build_parser()
    assert "Wattlas" in parser.description


def test_refresh_script_sets_pipeline_source_path() -> None:
    script = (Path(__file__).parents[2] / "scripts" / "refresh-snapshot.sh").read_text()
    assert 'PYTHONPATH="$ROOT/pipeline/src"' in script


def test_merge_asset_feeds_assigns_country_and_keeps_official_precedence() -> None:
    countries = {"features": [{
        "type": "Feature", "id": "US",
        "geometry": {"type": "Polygon", "coordinates": [[[-100, 20], [-70, 20], [-70, 50], [-100, 50], [-100, 20]]]},
        "properties": {"id": "US", "country": "US", "level": "country"},
    }]}
    official = {"sources": [{"id": "official", "name": "Official", "tier": "A", "url": "https://example.com"}], "assets": [{
        "id": "official-campus", "name": "Alpha DC", "operator": "Alpha Cloud",
        "country": "US", "geographyId": "US", "category": "data_centre", "subtype": "hyperscale",
        "lifecycle": "under_construction", "targetYear": 2028, "coordinates": [-77.1, 38.9],
        "locationPrecision": "exact", "valueKind": "reported", "sourceIds": ["official"],
        "sourceType": "official_verified", "sourceUrl": "https://example.com", "externalIds": {"osm": "node/101"},
        "demandMw": {"low": 90, "central": 100, "high": 120},
    }]}
    osm = {"assets": [{
        "id": "osm-node-101", "name": "Alpha DC", "operator": "Alpha Cloud", "geographyId": "UNASSIGNED",
        "category": "data_centre", "subtype": "other_data_centre", "lifecycle": "operational",
        "targetYear": None, "coordinates": [-77.1, 38.9], "locationPrecision": "exact", "valueKind": "observed",
        "sourceIds": ["openstreetmap-infrastructure"], "sourceType": "community_mapped",
        "sourceUrl": "https://www.openstreetmap.org/node/101", "externalIds": {"osm": "node/101"}, "demandMw": None,
    }]}

    merged = merge_asset_feeds(countries, official, osm, observed_at="2026-06-27T12:00:00Z")

    assert len(merged["assets"]) == 1
    assert merged["assets"][0]["id"] == "official-campus"
    assert merged["assets"][0]["country"] == "US"
    assert merged["assets"][0]["demandMw"]["central"] == 100
    assert {source["id"] for source in merged["sources"]} == {"official", "openstreetmap-infrastructure"}


def test_power_sources_and_refresh_steps_have_approved_precedence() -> None:
    assert POWER_SOURCE_PRECEDENCE == (
        "official_power", "gem_power", "wri_power", "osm_power"
    )
    assert REFRESH_STEPS == (
        "boundaries", "population", "plant_sources", "plant_canonicalization",
        "country_electricity_controls", "official_adm1_observations",
        "modelled_adm1_residual_demand", "supply_balance_forecast", "scores",
        "artifacts", "validation", "atomic_publish",
    )


def test_raw_capture_store_returns_source_specific_last_known_good(tmp_path) -> None:
    store = RawCaptureStore(tmp_path / "raw", tmp_path / "warehouse.duckdb")
    store.save("gem_power", b'{"records":[{"id":"gem"}]}', "application/json")
    store.save("wri_power", b'{"records":[{"id":"wri"}]}', "application/json")

    capture = store.latest_capture("gem_power")

    assert capture is not None
    assert json.loads(capture.path.read_text())["records"][0]["id"] == "gem"
    assert capture.source_id == "gem_power"
    assert capture.retrieved_at.tzinfo is not None


def test_model_artifacts_are_loaded_and_version_checked_without_raster_rebuild(tmp_path) -> None:
    population = tmp_path / "population.json"
    weights = tmp_path / "weights.json"
    population.write_text(json.dumps({
        "schemaVersion": "wattlas-adm1-population-v1",
        "roundingMethod": "largest-remainder-integer-v1",
        "sources": [{"id": "worldpop", "url": "https://example.com", "licence": "CC-BY-4.0"}],
        "sourceReleases": [{"sourceId": "worldpop", "releaseId": "r1", "checksumSha256": "a" * 64, "retrievedAt": "2026-01-01T00:00:00Z"}],
        "records": [], "unavailable": [],
        "buildInputs": {"boundaryFingerprint": "sha256:" + "b" * 64, "officialOverrideFingerprint": "sha256:" + "c" * 64, "countryControlFingerprint": "sha256:" + "d" * 64, "methodVersions": {"schema": "wattlas-adm1-population-v1", "zonal": "raster-mask-sum-v2", "reconciliation": "largest-remainder-integer-v1"}},
        "effectiveInputFingerprint": "sha256:" + "e" * 64,
        "buildFingerprint": "sha256:" + "f" * 64,
    }))
    # The population loader validates its own cryptographic seal, so this test
    # deliberately exercises the lightweight daily metadata gate only.
    weights.write_text(json.dumps({
        "schemaVersion": "wattlas-regional-demand-weights-v1",
        "effectiveInputFingerprint": "sha256:" + "1" * 64,
        "buildFingerprint": "sha256:" + "2" * 64,
        "buildInputs": {"populationFingerprint": "sha256:" + "f" * 64},
        "records": [],
    }))

    loaded = load_refresh_model_artifacts(population, weights, validate_population=False)

    assert loaded["population"]["buildFingerprint"].startswith("sha256:")
    assert loaded["demandWeights"]["schemaVersion"].endswith("weights-v1")


def test_model_artifacts_reject_unbuilt_weight_release(tmp_path) -> None:
    population = tmp_path / "population.json"
    weights = tmp_path / "weights.json"
    population.write_text('{"schemaVersion":"wattlas-adm1-population-v1","buildFingerprint":"sha256:' + "a" * 64 + '"}')
    weights.write_text('{"schemaVersion":"wattlas-regional-demand-weights-v1","buildFingerprint":"sha256:unbuilt","effectiveInputFingerprint":"sha256:unbuilt","buildInputs":{"populationFingerprint":"sha256:' + "a" * 64 + '"},"records":[]}')

    with pytest.raises(ValueError, match="unbuilt"):
        load_refresh_model_artifacts(population, weights, validate_population=False)


def test_model_artifacts_reject_population_weight_release_mismatch(tmp_path) -> None:
    population = tmp_path / "population.json"
    weights = tmp_path / "weights.json"
    population.write_text('{"schemaVersion":"wattlas-adm1-population-v1","buildFingerprint":"sha256:' + "a" * 64 + '"}')
    weights.write_text('{"schemaVersion":"wattlas-regional-demand-weights-v1","buildFingerprint":"sha256:' + "b" * 64 + '","effectiveInputFingerprint":"sha256:' + "c" * 64 + '","buildInputs":{"populationFingerprint":"sha256:' + "d" * 64 + '"},"records":[]}')

    with pytest.raises(ValueError, match="population release"):
        load_refresh_model_artifacts(population, weights, validate_population=False)


def test_connector_status_separates_check_time_from_observation_date() -> None:
    result = ConnectorResult(
        source_id="gem_power",
        state=ConnectorState.CURRENT,
        payload=FetchPayload(
            source_id="gem_power",
            retrieved_at=datetime(2026, 6, 30, tzinfo=UTC),
            media_type="application/json",
            body=b'{"records":[{"updatedAt":"2025-12-31"}]}',
        ),
    )

    status = build_connector_status(result, checked_at="2026-06-30T04:00:00Z")

    assert status["checkedAt"] == "2026-06-30T04:00:00Z"
    assert status["observationDate"] == "2025-12-31"
    assert status["lastSuccessAt"] == "2026-06-30T04:00:00Z"

    cached = build_connector_status(
        ConnectorResult(
            source_id="gem_power", state=ConnectorState.CACHED,
            payload=None, message="Using last successful capture",
        ),
        checked_at="2026-07-01T04:00:00Z",
        observation_body=result.payload.body,
        last_success_at="2026-06-30T04:00:00Z",
    )
    assert cached["checkedAt"] == "2026-07-01T04:00:00Z"
    assert cached["lastSuccessAt"] == "2026-06-30T04:00:00Z"
    assert cached["observationDate"] == "2025-12-31"


def test_optional_source_uses_its_own_last_known_good_capture(tmp_path) -> None:
    store = RawCaptureStore(tmp_path / "raw", tmp_path / "warehouse.duckdb")
    store.save("gem_power", b'{"records":[{"id":"cached-gem"}]}', "application/json")

    body, status = _optional_network_result(
        lambda: (_ for _ in ()).throw(RuntimeError("release temporarily unavailable")),
        "gem_power",
        store,
    )

    assert json.loads(body)["records"][0]["id"] == "cached-gem"
    assert status.state == ConnectorState.CACHED
    assert "last successful" in (status.message or "")


def test_optional_unconfigured_source_is_empty_without_masking_other_sources(tmp_path) -> None:
    store = RawCaptureStore(tmp_path / "raw", tmp_path / "warehouse.duckdb")
    result = ConnectorResult(
        source_id="gem_power", state=ConnectorState.NOT_CONFIGURED,
        payload=None, message="optional local GEM release not configured",
    )

    body, status = _optional_network_result(lambda: result, "gem_power", store)

    assert json.loads(body) == {"records": []}
    assert status.state == ConnectorState.NOT_CONFIGURED


def test_power_record_collection_is_deterministic_and_source_ordered() -> None:
    payloads = {
        "osm_power": b'{"records":[{"id":"osm"}]}',
        "official_power": b'{"records":[{"id":"official"}]}',
        "wri_power": b'{"records":[{"id":"wri"}]}',
        "gem_power": b'{"records":[{"id":"gem"}]}',
    }

    records, counts = collect_power_source_records(payloads)

    assert [row["id"] for row in records] == ["official", "gem", "wri", "osm"]
    assert counts == {name: 1 for name in POWER_SOURCE_PRECEDENCE}


def test_refresh_quality_rejects_reconciliation_and_coverage_drops() -> None:
    previous = {"coverage": {"canonicalPowerPlants": 100, "generatorRegions": 8}}
    current = {
        "coverage": {
            "canonicalPowerPlants": 99, "generatorRegions": 8,
            "powerSourceRecords": 120, "canonicalPowerUnits": 140,
        },
        "quality": {"countryDemandReconciled": True, "generatorArtifactsReconciled": True},
    }
    with pytest.raises(ValueError, match="coverage drop"):
        validate_refresh_quality(current, previous)

    current["coverage"]["canonicalPowerPlants"] = 100
    current["quality"]["countryDemandReconciled"] = False
    with pytest.raises(ValueError, match="reconciliation"):
        validate_refresh_quality(current, previous)


def test_regional_model_preserves_official_demand_and_allocates_residual() -> None:
    root = Path(__file__).parents[2]
    weights = []
    for year in range(2026, 2032):
        weights.extend([
            {"geographyId": "USA-A", "countryIso3": "USA", "year": year,
             "populationShare": 0.6, "activityShare": None, "industrialShare": None,
             "sourceIds": ["population-release"], "coverage": 100},
            {"geographyId": "USA-B", "countryIso3": "USA", "year": year,
             "populationShare": 0.4, "activityShare": None, "industrialShare": None,
             "sourceIds": ["population-release"], "coverage": 100},
        ])
    official = [{
        "geographyId": "USA-A", "countryIso3": "USA", "year": 2026,
        "demandGwh": 700, "sourceIds": ["official-state-series"],
        "sourceId": "official-state-series", "sourceType": "official_verified",
        "sourceUrl": "https://example.gov/series", "licence": "CC0-1.0",
        "valueKind": "reported", "methodId": "official-direct-v1",
        "confidence": 98, "coverage": 100,
    }]

    forecasts, reconciled = build_regional_energy_model(
        demand_weights={"records": weights},
        country_controls=[{
            "countryIso3": "USA", "year": 2025, "demandGwh": 1000,
            "sourceIds": ["country-series"], "valueKind": "reported",
            "methodId": "country-control-v1", "confidence": 90, "coverage": 100,
        }],
        official_observations=official,
        power_records=[],
        assumptions=load_generation_assumptions(root / "data/curated/generation-assumptions.json"),
        method_config=load_regional_demand_methods(root / "data/curated/regional-demand-methods.json"),
    )

    assert reconciled is True
    assert forecasts["USA-A"][0]["metrics"]["demandGwh"]["central"] == 700
    assert forecasts["USA-B"][0]["metrics"]["demandGwh"]["central"] == 300
    assert [row["year"] for row in forecasts["USA-B"]] == list(range(2026, 2032))
