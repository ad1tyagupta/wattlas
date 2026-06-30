from datetime import UTC, datetime
from hashlib import sha256
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
    _local_records_with_lkg,
    _generator_artifacts_reconcile,
    build_forward_demand_increments,
    run_refresh_stage_sequence,
    _fetch_eia_observations,
    _field_lineage,
)
from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState
from grid_scope.storage import RawCaptureStore
from grid_scope.power_balance import load_generation_assumptions
from grid_scope.power_plants import canonicalize_power_plants
from grid_scope.regional_demand import (
    build_regional_demand_weights,
    load_regional_demand_methods,
)


def _sealed_weights(population_fingerprint: str, records: list[dict]) -> dict:
    build_inputs = {"populationFingerprint": population_fingerprint}
    fingerprint = lambda value: "sha256:" + sha256(json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()).hexdigest()
    artifact = {
        "schemaVersion": "wattlas-regional-demand-weights-v1",
        "effectiveInputFingerprint": fingerprint(build_inputs),
        "buildInputs": build_inputs,
        "records": records,
    }
    artifact["buildFingerprint"] = fingerprint(artifact)
    return artifact


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
    assert 'for artifact in "$ADM1_POPULATION_ARTIFACT_PATH" "$REGIONAL_DEMAND_WEIGHTS_PATH"' in script
    assert "refusing to publish" in script


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
        "records": [{"geographyId": "AA-1", "year": 2030, "population": 1}], "unavailable": [],
        "buildInputs": {"boundaryFingerprint": "sha256:" + "b" * 64, "officialOverrideFingerprint": "sha256:" + "c" * 64, "countryControlFingerprint": "sha256:" + "d" * 64, "methodVersions": {"schema": "wattlas-adm1-population-v1", "zonal": "raster-mask-sum-v2", "reconciliation": "largest-remainder-integer-v1"}},
        "effectiveInputFingerprint": "sha256:" + "e" * 64,
        "buildFingerprint": "sha256:" + "f" * 64,
    }))
    # The population loader validates its own cryptographic seal, so this test
    # deliberately exercises the lightweight daily metadata gate only.
    weights.write_text(json.dumps(_sealed_weights(
        "sha256:" + "f" * 64,
        [{"geographyId": "AA-1", "countryIso3": "AAA", "year": 2030}],
    )))

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
    weights.write_text(json.dumps(_sealed_weights("sha256:" + "d" * 64, [])))

    with pytest.raises(ValueError, match="population release"):
        load_refresh_model_artifacts(population, weights, validate_population=False)


def test_model_artifacts_reject_tampered_demand_weight_content(tmp_path) -> None:
    population_fingerprint = "sha256:" + "a" * 64
    population_records = [{
        "geographyId": "AA-1", "country": "AA", "year": year,
        "population": 100, "sourceIds": ["worldpop"],
    } for year in range(2026, 2032)]
    artifact = build_regional_demand_weights(
        population_artifact={
            "buildFingerprint": population_fingerprint,
            "records": population_records,
        },
        active_geography_ids={"AA-1"},
    )
    population = tmp_path / "population.json"
    weights = tmp_path / "weights.json"
    population.write_text(json.dumps({
        "schemaVersion": "wattlas-adm1-population-v1",
        "buildFingerprint": population_fingerprint,
        "records": population_records,
    }))
    artifact["records"][0]["populationShare"] = 0.5
    weights.write_text(json.dumps(artifact))

    with pytest.raises(ValueError, match="integrity|fingerprint"):
        load_refresh_model_artifacts(population, weights, validate_population=False)


@pytest.mark.parametrize("missing", ["population", "weights"])
def test_model_artifacts_are_mandatory_and_never_accept_empty_releases(
    tmp_path, missing
) -> None:
    population = tmp_path / "population.json"
    weights = tmp_path / "weights.json"
    population.write_text(json.dumps({
        "schemaVersion": "wattlas-adm1-population-v1",
        "buildFingerprint": "sha256:" + "a" * 64,
        "records": [{"geographyId": "AA-1", "year": 2030, "population": 1}],
    }))
    weights.write_text(json.dumps(_sealed_weights(
        "sha256:" + "a" * 64,
        [{"geographyId": "AA-1", "countryIso3": "AAA", "year": 2030}],
    )))
    (population if missing == "population" else weights).unlink()
    with pytest.raises((FileNotFoundError, ValueError)):
        load_refresh_model_artifacts(population, weights, validate_population=False)

    # Recreate the missing file, then prove zero-record releases are also blocked.
    if missing == "population":
        population.write_text(json.dumps({
            "schemaVersion": "wattlas-adm1-population-v1",
            "buildFingerprint": "sha256:" + "a" * 64,
            "records": [],
        }))
    else:
        weights.write_text(json.dumps(_sealed_weights("sha256:" + "a" * 64, [])))
    with pytest.raises(ValueError, match="non-empty records"):
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


def test_connector_status_rejects_malformed_dates_instead_of_relabeling_check_time() -> None:
    result = ConnectorResult(
        source_id="wri_power", state=ConnectorState.CURRENT,
        payload=FetchPayload(
            source_id="wri_power", retrieved_at=datetime(2026, 6, 30, tzinfo=UTC),
            media_type="application/json",
            body=b'{"records":[{"updatedAt":"not-a-date"}]}',
        ),
    )
    status = build_connector_status(result, checked_at="2026-06-30T04:00:00Z")
    assert status["observationDate"] is None
    assert status["checkedAt"] == "2026-06-30T04:00:00Z"

    osm = build_connector_status(
        ConnectorResult(
            source_id="osm_power", state=ConnectorState.CURRENT,
            payload=FetchPayload(
                source_id="osm_power", retrieved_at=datetime(2026, 6, 30, tzinfo=UTC),
                media_type="application/json",
                body=b'{"records":[{"updatedAt":"2026-06-30T04:00:00Z"}]}',
            ),
        ),
        checked_at="2026-06-30T04:00:00Z",
    )
    assert osm["observationDate"] is None


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


def test_gem_material_fields_outrank_wri_for_the_same_plant() -> None:
    common = {
        "name": "Alpha Power Station", "country": "AA", "countryIso3": "AAA",
        "geographyId": "AA-1", "coordinates": [10.0, 20.0], "technology": "gas",
        "lifecycle": "operational", "locationPrecision": "exact",
        "valueKind": "reported", "sourceType": "research_verified",
        "externalIds": {"wikidata": "Q123"},
    }
    wri = {**common, "id": "wri-alpha", "capacityMw": 130,
           "sourceIds": ["wri_power"], "externalIds": {**common["externalIds"], "wri": "1"}}
    gem = {**common, "id": "gem-alpha", "capacityMw": 120,
           "sourceIds": ["gem_power"], "externalIds": {**common["externalIds"], "gemplant": "G1"}}
    result = canonicalize_power_plants([wri, gem])
    assert len(result["records"]) == 1
    assert result["records"][0]["capacityMw"]["central"] == 120


def test_refresh_quality_rejects_reconciliation_and_coverage_drops() -> None:
    previous = {"coverage": {
        "canonicalPowerPlants": 100, "canonicalPowerUnits": 140,
        "generatorRegions": 8, "regionalEnergyRegions": 8,
        "powerSourceRecords": 120, "publishedPowerPlants": 90,
        "countries": 1, "admin1Regions": 8,
    }}
    current = {
        "coverage": {
            "canonicalPowerPlants": 99, "generatorRegions": 8,
            "powerSourceRecords": 120, "canonicalPowerUnits": 140,
            "regionalEnergyRegions": 8, "publishedPowerPlants": 90,
            "countries": 1, "admin1Regions": 8,
        },
        "quality": {"countryDemandReconciled": True, "generatorArtifactsReconciled": True},
    }
    with pytest.raises(ValueError, match="coverage drop"):
        validate_refresh_quality(current, previous)

    current["coverage"]["canonicalPowerPlants"] = 100
    current["quality"]["countryDemandReconciled"] = False
    with pytest.raises(ValueError, match="reconciliation"):
        validate_refresh_quality(current, previous)


def test_refresh_quality_requires_all_new_coverage_gates_and_blocks_collapse() -> None:
    coverage = {
        "countries": 1, "admin1Regions": 2, "canonicalPowerPlants": 3,
        "canonicalPowerUnits": 3, "generatorRegions": 2,
        "regionalEnergyRegions": 2, "powerSourceRecords": 4,
        "publishedPowerPlants": 3,
    }
    current = {"coverage": dict(coverage), "quality": {
        "countryDemandReconciled": True, "generatorArtifactsReconciled": True,
    }}
    for required in ("regionalEnergyRegions", "powerSourceRecords", "publishedPowerPlants"):
        invalid = {**current, "coverage": dict(coverage)}
        invalid["coverage"].pop(required)
        with pytest.raises(ValueError, match=required):
            validate_refresh_quality(invalid)
        zero = {**current, "coverage": dict(coverage)}
        zero["coverage"][required] = 0
        with pytest.raises(ValueError, match=required):
            validate_refresh_quality(zero)
    previous = {"coverage": dict(coverage)}
    current["coverage"]["publishedPowerPlants"] = 2
    with pytest.raises(ValueError, match="coverage drop.*publishedPowerPlants"):
        validate_refresh_quality(current, previous)


def test_generator_reconciliation_is_computed_from_artifact_contents() -> None:
    shard = {"type": "FeatureCollection", "features": [{
        "id": "plant-1", "properties": {"geographyId": "AA-1"},
    }]}
    artifacts = {
        "generator-overview.geojson": json.dumps({
            "type": "FeatureCollection",
            "features": [{"properties": {"geographyId": "AA-1", "count": 1}}],
        }).encode(),
        "generators/index.json": json.dumps({
            "countries": {"AA": {"path": "generators/AA.geojson", "featureCount": 1}},
            "totals": {"featureCount": 1},
        }).encode(),
        "generators/AA.geojson": json.dumps(shard).encode(),
    }
    assert _generator_artifacts_reconcile(artifacts, expected_plants=1) is True
    broken = dict(artifacts)
    broken["generators/index.json"] = json.dumps({
        "countries": {"AA": {"path": "generators/AA.geojson", "featureCount": 1}},
        "totals": {"featureCount": 99},
    }).encode()
    assert _generator_artifacts_reconcile(broken, expected_plants=1) is False


def test_source_specific_normalized_release_uses_last_known_good_on_invalid_current(tmp_path) -> None:
    store = RawCaptureStore(tmp_path / "raw", tmp_path / "warehouse.duckdb")
    first, first_status = _local_records_with_lkg(
        lambda: [{"id": "good"}], source_id="ember-country-controls", store=store,
        now=datetime(2026, 6, 30, tzinfo=UTC), configured=True,
    )
    second, second_status = _local_records_with_lkg(
        lambda: (_ for _ in ()).throw(ValueError("invalid new release")),
        source_id="ember-country-controls", store=store,
        now=datetime(2026, 7, 1, tzinfo=UTC), configured=True,
    )
    assert first == second == [{"id": "good"}]
    assert first_status.state == ConnectorState.CURRENT
    assert second_status.state == ConnectorState.CACHED
    empty, empty_status = _local_records_with_lkg(
        lambda: [], source_id="ember-country-controls", store=store,
        now=datetime(2026, 7, 2, tzinfo=UTC), configured=True,
    )
    assert empty == [{"id": "good"}]
    assert empty_status.state == ConnectorState.CACHED


def test_configured_eia_is_fetched_across_all_public_state_routes(
    tmp_path, monkeypatch
) -> None:
    import grid_scope.cli as cli_module

    routes = []

    class FakeEiaConnector:
        def __init__(self, *, base_url, api_key):
            assert base_url == "https://api.eia.gov/v2/"

        def fetch(self, *, route_id, params, now, client):
            routes.append(route_id)
            assert params["frequency"] == "annual"
            body = json.dumps({"route": route_id}).encode()
            return ConnectorResult(
                source_id="eia-api-v2", state=ConnectorState.CURRENT,
                payload=FetchPayload("eia-api-v2", now, "application/json", body),
            )

    monkeypatch.setenv("EIA_API_V2_URL", "https://api.eia.gov/v2/")
    monkeypatch.setattr(cli_module, "EiaV2Connector", FakeEiaConnector)
    monkeypatch.setattr(
        cli_module, "normalize_eia_state",
        lambda payload, **kwargs: [{"route": payload["route"]}],
    )
    monkeypatch.setattr(cli_module, "merge_regional_observations", lambda rows: list(rows))
    store = RawCaptureStore(tmp_path / "raw", tmp_path / "warehouse.duckdb")
    records, status = _fetch_eia_observations(
        object(), now=datetime(2026, 6, 30, tzinfo=UTC), store=store,
        admin1_payload={"features": [{"properties": {
            "id": "US-TEXAS", "country": "US", "name": "Texas",
        }}]},
    )
    assert routes == ["sales", "generation", "capability"]
    assert [row["route"] for row in records] == routes
    assert status.state == ConnectorState.CURRENT


def test_refresh_executes_the_approved_stage_order_via_instrumented_calls() -> None:
    observed = []
    callbacks = {step: (lambda step=step: observed.append(step)) for step in REFRESH_STEPS}
    run_refresh_stage_sequence(callbacks)
    assert observed == list(REFRESH_STEPS)


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


def test_regional_model_uses_every_official_field_and_forward_increment_once() -> None:
    root = Path(__file__).parents[2]
    weights = [{
        "geographyId": "USA-A", "countryIso3": "USA", "year": year,
        "populationShare": 1, "activityShare": None, "industrialShare": None,
        "sourceIds": ["population-release"], "coverage": 100,
    } for year in range(2026, 2032)]
    official = [{
        "geographyId": "USA-A", "countryIso3": "USA", "year": 2026,
        "demandGwh": 1000, "localGenerationGwh": 800, "peakDemandMw": 250,
        "installedCapacityMw": 300, "dependableCapacityMw": 200,
        "generationMixGwh": {"gas": 700, "solar": 100},
        "sourceIds": ["eia-api-v2"], "sourceId": "eia-api-v2",
        "sourceType": "official_verified", "valueKind": "reported",
        "methodId": "official-direct-v1", "confidence": 98, "coverage": 100,
    }]
    increments = [{
        "incrementId": "dc-2026", "geographyId": "USA-A", "targetYear": 2026,
        "demandGwh": {"low": 87.6, "central": 87.6, "high": 87.6},
        "sourceIds": ["dc-source"],
    }]
    observed = []
    forecasts, reconciled = build_regional_energy_model(
        demand_weights={"records": weights},
        country_controls=[{
            "countryIso3": "USA", "year": 2026, "demandGwh": 1000,
            "sourceIds": ["country-series"], "valueKind": "reported",
            "methodId": "country-control-v1", "confidence": 90, "coverage": 100,
        }],
        official_observations=official, power_records=[], demand_increments=increments,
        assumptions=load_generation_assumptions(root / "data/curated/generation-assumptions.json"),
        method_config=load_regional_demand_methods(root / "data/curated/regional-demand-methods.json"),
        before_supply=lambda: observed.append("supply"),
    )
    metrics = forecasts["USA-A"][0]["metrics"]
    assert reconciled is True
    assert metrics["demandGwh"]["central"] == pytest.approx(1087.6)
    assert metrics["peakDemandMw"]["central"] == 250
    assert metrics["localGenerationGwh"]["central"] == 800
    assert metrics["installedCapacityMw"] == 300
    assert metrics["dependableCapacityMw"]["central"] == 200
    assert metrics["generationMixGwh"] == {"gas": 700, "solar": 100}
    assert forecasts["USA-A"][0]["appliedIncrementIds"] == ["dc-2026"]
    assert forecasts["USA-A"][1]["appliedIncrementIds"] == []
    assert forecasts["USA-A"][0]["metrics"]["metricLineage"]["demandGwh"]["sourceIds"] == [
        "dc-source", "eia-api-v2",
    ]
    assert observed == ["supply"]


def test_regional_model_preserves_mixed_field_specific_official_lineage() -> None:
    root = Path(__file__).parents[2]
    weights = [{
        "geographyId": "USA-A", "countryIso3": "USA", "year": year,
        "populationShare": 1, "activityShare": None, "industrialShare": None,
        "sourceIds": ["population-release"], "coverage": 100,
    } for year in range(2026, 2032)]
    field_sources = {
        "demandGwh": "curated-demand", "localGenerationGwh": "eia-generation",
        "peakDemandMw": "curated-peak", "installedCapacityMw": "eia-installed",
        "dependableCapacityMw": "eia-capability", "netInterchangeGwh": "curated-net",
        "observedUnmetDemandGwh": "curated-unmet",
        "generationMixGwh.gas": "eia-generation-mix",
    }
    field_provenance = {
        field: {
            "sourceId": source, "sourceRecordId": f"{source}-record",
            "sourceType": "official_verified", "sourceUrl": "https://example.gov/data",
            "licence": "CC0-1.0", "updatedAt": "2026-01-02",
            "observationDate": "2026-01-01", "freshnessDays": 1,
            "valueKind": "reported", "methodId": f"{source}-method",
        }
        for field, source in field_sources.items()
    }
    observation = {
        "geographyId": "USA-A", "geographyLevel": "admin_1",
        "countryIso3": "USA", "year": 2026, "period": "annual",
        "demandGwh": 1000, "localGenerationGwh": 800, "peakDemandMw": 250,
        "installedCapacityMw": 300, "dependableCapacityMw": 200,
        "netInterchangeGwh": 50, "observedUnmetDemandGwh": 10,
        "generationMixGwh": {"gas": 800}, "fieldProvenance": field_provenance,
        "sourceIds": [*field_sources.values(), "unused-evidence"],
        "sourceId": "unused-evidence", "sourceType": "official_verified",
        "valueKind": "reported", "methodId": "unused-method",
    }
    forecasts, _ = build_regional_energy_model(
        demand_weights={"records": weights},
        country_controls=[{
            "countryIso3": "USA", "year": 2026, "demandGwh": 1000,
            "sourceIds": ["country-series"], "valueKind": "reported",
            "methodId": "country-control-v1", "confidence": 90, "coverage": 100,
        }],
        official_observations=[observation], power_records=[],
        assumptions=load_generation_assumptions(root / "data/curated/generation-assumptions.json"),
        method_config=load_regional_demand_methods(root / "data/curated/regional-demand-methods.json"),
    )
    row = forecasts["USA-A"][0]
    lineage = row["metrics"]["metricLineage"]
    for field, source in field_sources.items():
        assert lineage[field]["sourceIds"] == [source]
        assert lineage[field]["methodId"] == f"{source}-method"
    assert "unused-evidence" not in row["sourceIds"]
    contributions = {item["id"]: item for item in row["powerBalance"]["contributions"]}
    assert contributions["capacity_margin"]["sourceIds"] == [
        "curated-peak", "eia-capability",
    ]
    assert contributions["annual_local_balance"]["sourceIds"] == [
        "curated-demand", "eia-generation",
    ]
    assert contributions["observed_unmet_demand"]["sourceIds"] == ["curated-unmet"]
    assert contributions["forecast_demand_growth"]["sourceIds"] == ["curated-demand"]


def test_field_lineage_falls_back_only_for_complete_legacy_observations() -> None:
    legacy = {
        "sourceIds": ["legacy-official"], "methodId": "legacy-method-v1",
        "valueKind": "reported",
    }
    assert _field_lineage(legacy, "demandGwh")["sourceIds"] == ["legacy-official"]
    with pytest.raises(ValueError, match="field-specific provenance"):
        _field_lineage({**legacy, "fieldProvenance": {}}, "demandGwh")
    with pytest.raises(ValueError, match="source IDs"):
        _field_lineage({"methodId": "legacy-method-v1", "valueKind": "reported"}, "demandGwh")


def test_asset_forward_increments_include_only_sourced_adm1_future_loads() -> None:
    increments = build_forward_demand_increments({"assets": [{
        "id": "water-1", "geographyId": "AA-1", "category": "water_infrastructure",
        "lifecycle": "under_construction", "targetYear": 2028,
        "demandMw": {"low": 10, "central": 20, "high": 30},
        "sourceIds": ["water-source"],
    }, {
        "id": "country-only", "geographyId": "AA", "category": "data_centre",
        "lifecycle": "announced", "targetYear": 2028,
        "demandMw": {"low": 100, "central": 100, "high": 100},
        "sourceIds": ["dc-source"],
    }]}, active_admin1={"AA-1"})
    assert increments == [{
        "incrementId": "water-1:2028", "geographyId": "AA-1", "targetYear": 2028,
        "demandGwh": {"low": 87.6, "central": 175.2, "high": 262.8},
        "sourceIds": ["water-source"],
    }]
