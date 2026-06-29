from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from grid_scope.regional_demand import (
    add_forward_demand_increments,
    allocate_country_demand,
    build_regional_demand_weights,
    load_regional_demand_methods,
    write_regional_demand_weights,
)


def _region(
    geography_id: str,
    *,
    population: float | None,
    activity: float | None = None,
    industrial: float | None = None,
) -> dict:
    return {
        "id": geography_id,
        "countryIso3": "AAA",
        "populationShare": population,
        "activityShare": activity,
        "industrialShare": industrial,
        "sourceIds": ["weights-public-v1"],
        "coverage": 92,
    }


def _control(value: float = 1_000) -> dict:
    return {
        "demandGwh": value,
        "countryIso3": "AAA",
        "year": 2024,
        "sourceIds": ["country-control-public-v1"],
        "sourceUrl": "https://example.org/control",
        "valueKind": "reported",
        "methodId": "country-observation-v1",
        "confidence": 95,
        "coverage": 100,
    }


def test_modelled_regions_reconcile_exactly_to_country_control() -> None:
    result = allocate_country_demand(
        country_control=_control(),
        regions=[
            _region("AA-2", population=0.6, activity=0.5),
            _region("AA-1", population=0.4, activity=0.5),
        ],
    )

    assert math.fsum(item["demandGwh"]["central"] for item in result) == pytest.approx(
        1_000, rel=1e-6
    )
    assert [item["geographyId"] for item in result] == ["AA-1", "AA-2"]
    assert all(item["valueKind"] == "estimated" for item in result)
    assert all(item["methodGrade"] == "multi_covariate" for item in result)


def test_documented_country_gwh_convenience_api_is_transparent() -> None:
    result = allocate_country_demand(
        country_gwh=1_000,
        regions=[
            {"id": "AA-1", "populationShare": 0.4, "activityShare": 0.5},
            {"id": "AA-2", "populationShare": 0.6, "activityShare": 0.5},
        ],
    )
    assert math.fsum(item["demandGwh"]["central"] for item in result) == pytest.approx(1_000)
    assert all("regional-weight-unspecified" in item["sourceIds"] for item in result)


def test_official_regions_are_fixed_and_only_residual_is_modelled() -> None:
    official = {
        "geographyId": "AA-1",
        "countryIso3": "AAA",
        "year": 2024,
        "demandGwh": {"low": 195, "central": 200, "high": 210},
        "sourceIds": ["official-regional-a"],
        "sourceUrl": "https://example.org/official",
        "valueKind": "observed",
        "methodId": "official-direct-v1",
        "confidence": 99,
        "coverage": 100,
    }
    result = allocate_country_demand(
        country_control=_control(),
        regions=[_region("AA-1", population=0.2), _region("AA-2", population=0.3), _region("AA-3", population=0.5)],
        official_observations=[official],
    )

    by_id = {item["geographyId"]: item for item in result}
    assert by_id["AA-1"]["demandGwh"] == {"low": 195.0, "central": 200.0, "high": 210.0}
    assert by_id["AA-1"]["methodGrade"] == "official"
    assert math.fsum(by_id[key]["demandGwh"]["central"] for key in ("AA-2", "AA-3")) == pytest.approx(800)


def test_invalid_official_residuals_and_duplicate_ids_reject() -> None:
    over = {
        "geographyId": "AA-1", "countryIso3": "AAA", "year": 2024,
        "demandGwh": 1_001, "sourceIds": ["official-a"], "valueKind": "reported",
        "methodId": "official-direct-v1", "confidence": 100, "coverage": 100,
    }
    with pytest.raises(ValueError, match="official.*exceeds"):
        allocate_country_demand(country_control=_control(), regions=[_region("AA-1", population=1)], official_observations=[over])
    with pytest.raises(ValueError, match="without modelled"):
        allocate_country_demand(country_control=_control(), regions=[_region("AA-1", population=1)], official_observations=[{**over, "demandGwh": 900}])
    with pytest.raises(ValueError, match="duplicate geography"):
        allocate_country_demand(country_control=_control(), regions=[_region("AA-1", population=1), _region("AA-1", population=1)])
    with pytest.raises(ValueError, match="duplicate official"):
        allocate_country_demand(country_control=_control(), regions=[_region("AA-1", population=1)], official_observations=[{**over, "demandGwh": 500}, {**over, "demandGwh": 500}])


def test_missing_covariates_renormalize_and_disclose_effective_inputs() -> None:
    result = allocate_country_demand(
        country_control=_control(),
        regions=[
            _region("AA-1", population=0.4, activity=0.7, industrial=None),
            _region("AA-2", population=0.6, activity=None, industrial=None),
        ],
    )
    by_id = {item["geographyId"]: item for item in result}
    assert by_id["AA-1"]["effectiveWeights"] == pytest.approx({"activity": 0.55 / 0.85, "population": 0.30 / 0.85})
    assert by_id["AA-1"]["effectiveDenominator"] == pytest.approx(0.85)
    assert by_id["AA-2"]["effectiveWeights"] == {"population": 1.0}
    assert by_id["AA-2"]["methodGrade"] == "population_only"
    assert by_id["AA-2"]["covariates"]["activity"]["available"] is False
    assert by_id["AA-2"]["covariates"]["activity"]["share"] is None


def test_population_only_is_wider_and_older_sources_widen_bands() -> None:
    young = allocate_country_demand(
        country_control=_control(),
        regions=[_region("AA-1", population=1)],
        as_of_year=2025,
        covariate_year=2025,
    )[0]
    old = allocate_country_demand(
        country_control=_control(),
        regions=[_region("AA-1", population=1)],
        as_of_year=2025,
        covariate_year=2020,
    )[0]
    assert young["demandGwh"]["low"] <= young["demandGwh"]["central"] <= young["demandGwh"]["high"]
    assert old["demandGwh"]["low"] < young["demandGwh"]["low"]
    assert old["demandGwh"]["high"] > young["demandGwh"]["high"]
    assert old["confidence"] < young["confidence"]


def test_uncertainty_configuration_is_versioned_and_executable() -> None:
    methods = load_regional_demand_methods(
        Path(__file__).parents[2] / "data" / "curated" / "regional-demand-methods.json"
    )
    result = allocate_country_demand(
        country_control=_control(), regions=[_region("AA-1", population=1)],
        method_config=methods,
    )[0]
    assert result["uncertaintyFraction"] == 0.25
    assert methods["schemaVersion"] == "wattlas-regional-demand-methods-v1"


def test_lineage_is_complete_and_historical_control_is_not_asset_adjusted() -> None:
    result = allocate_country_demand(
        country_control=_control(100),
        regions=[_region("AA-1", population=1)],
    )[0]
    assert result["demandGwh"]["central"] == 100
    assert result["countryIso3"] == "AAA"
    assert result["year"] == 2024
    assert result["geographyLevel"] == "admin_1"
    assert result["sourceIds"] == ["country-control-public-v1", "weights-public-v1"]
    assert result["methodId"]
    assert result["valueKind"] == "estimated"
    assert 0 <= result["confidence"] <= 100
    assert 0 <= result["coverage"] <= 100


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_covariate_shares_reject_and_missing_is_not_zero(bad: float) -> None:
    with pytest.raises(ValueError, match="share"):
        allocate_country_demand(country_control=_control(), regions=[_region("AA-1", population=bad)])
    with pytest.raises(ValueError, match="population.*unavailable"):
        allocate_country_demand(country_control=_control(), regions=[_region("AA-1", population=None)])
    with pytest.raises(ValueError, match="country control"):
        allocate_country_demand(country_control={**_control(), "demandGwh": None}, regions=[_region("AA-1", population=1)])


def test_component_shares_are_normalized_deliberately() -> None:
    with pytest.raises(ValueError, match="activity.*sum"):
        allocate_country_demand(
            country_control=_control(),
            regions=[_region("AA-1", population=0.5, activity=0.8), _region("AA-2", population=0.5, activity=0.8)],
        )


def test_input_order_does_not_change_allocation() -> None:
    regions = [_region("AA-3", population=0.2, activity=0.1), _region("AA-1", population=0.3, activity=0.5), _region("AA-2", population=0.5, activity=0.4)]
    forward = allocate_country_demand(country_control=_control(), regions=regions)
    reverse = allocate_country_demand(country_control=_control(), regions=list(reversed(regions)))
    assert forward == reverse


def test_forward_increments_are_explicit_once_only_and_ordered() -> None:
    base = [{
        "geographyId": "AA-1", "countryIso3": "AAA", "year": 2026,
        "demandGwh": {"low": 90, "central": 100, "high": 110},
        "sourceIds": ["forecast-base"],
    }]
    increment = {
        "incrementId": "project-one-2027", "geographyId": "AA-1", "targetYear": 2027,
        "demandGwh": {"low": 5, "central": 10, "high": 20},
        "sourceIds": ["public-project-one"],
    }
    result = add_forward_demand_increments(base, [increment])
    assert result[0]["year"] == 2027
    assert result[0]["demandGwh"] == {"low": 95.0, "central": 110.0, "high": 130.0}
    assert result[0]["appliedIncrementIds"] == ["project-one-2027"]
    assert "public-project-one" in result[0]["sourceIds"]
    with pytest.raises(ValueError, match="duplicate increment"):
        add_forward_demand_increments(base, [increment, increment])
    with pytest.raises(ValueError, match="already applied"):
        add_forward_demand_increments(result, [increment])
    with pytest.raises(ValueError, match="2026.*2031"):
        add_forward_demand_increments(base, [{**increment, "targetYear": 2032}])
    with pytest.raises(ValueError, match="ordered"):
        add_forward_demand_increments(base, [{**increment, "demandGwh": {"low": 20, "central": 10, "high": 5}}])
    with pytest.raises(ValueError, match="source"):
        add_forward_demand_increments(base, [{**increment, "sourceIds": []}])


def test_forward_increment_keeps_prior_once_only_lineage() -> None:
    base = [{
        "geographyId": "AA-1", "countryIso3": "AAA", "year": 2027,
        "demandGwh": {"low": 90, "central": 100, "high": 110},
        "sourceIds": ["forecast-base", "project-zero-source"],
        "appliedIncrementIds": ["project-zero-2027"],
    }]
    result = add_forward_demand_increments(base, [{
        "incrementId": "project-one-2027", "geographyId": "AA-1", "targetYear": 2027,
        "demandGwh": {"low": 5, "central": 10, "high": 20},
        "sourceIds": ["project-one-source"],
    }])
    assert result[0]["appliedIncrementIds"] == ["project-one-2027", "project-zero-2027"]


def _population_artifact() -> dict:
    records = []
    for year in (2026, 2027):
        records.extend([
            {"geographyId": "AA-1", "country": "AA", "year": year, "population": 40, "sourceIds": ["worldpop"], "sourceUrl": "https://example.org/worldpop", "methodId": "worldpop-zonal", "valueKind": "estimated", "confidence": 80, "coverage": 100},
            {"geographyId": "AA-2", "country": "AA", "year": year, "population": 60, "sourceIds": ["worldpop"], "sourceUrl": "https://example.org/worldpop", "methodId": "worldpop-zonal", "valueKind": "estimated", "confidence": 80, "coverage": 100},
        ])
    return {"schemaVersion": "wattlas-admin1-population-v1", "buildFingerprint": "sha256:population", "records": records, "unavailable": []}


def test_weight_artifact_contains_only_normalized_compact_inputs_and_fingerprint(tmp_path: Path) -> None:
    artifact = build_regional_demand_weights(
        population_artifact=_population_artifact(),
        active_geography_ids={"AA-1", "AA-2"},
        activity_records=[{"geographyId": "AA-1", "year": 2026, "value": 30, "sourceId": "lights"}, {"geographyId": "AA-2", "year": 2026, "value": 70, "sourceId": "lights"}],
        industrial_records=[],
        official_observations=[{
            "geographyId": "AA-1", "country": "AA", "year": 2026,
            "sourceIds": ["official-aa"], "methodId": "official-direct-v1",
            "valueKind": "reported",
        }],
    )
    assert artifact["schemaVersion"] == "wattlas-regional-demand-weights-v1"
    assert artifact["records"][0]["populationShare"] == 0.4
    assert sum(row["populationShare"] for row in artifact["records"] if row["year"] == 2026) == pytest.approx(1)
    assert "population" not in artifact["records"][0]
    assert artifact["buildFingerprint"].startswith("sha256:")
    assert artifact["buildInputs"]["activeGeographyIds"] == ["AA-1", "AA-2"]
    assert artifact["officialObservationLineage"] == [{
        "country": "AA", "geographyId": "AA-1", "methodId": "official-direct-v1",
        "sourceIds": ["official-aa"], "valueKind": "reported", "year": 2026,
    }]
    assert "official-aa" in artifact["sources"]
    output = tmp_path / "weights.json"
    write_regional_demand_weights(artifact, output)
    assert json.loads(output.read_text()) == artifact
    with pytest.raises(ValueError, match="active ADM1"):
        build_regional_demand_weights(population_artifact=_population_artifact(), active_geography_ids={"AA-1"})
    with pytest.raises(ValueError, match="population geography-year"):
        build_regional_demand_weights(
            population_artifact=_population_artifact(), active_geography_ids={"AA-1", "AA-2"},
            activity_records=[{"geographyId": "AA-1", "year": 2031, "value": 1, "sourceId": "lights"}],
        )
    with pytest.raises(ValueError, match="source ID"):
        build_regional_demand_weights(
            population_artifact=_population_artifact(), active_geography_ids={"AA-1", "AA-2"},
            activity_records=[{"geographyId": "AA-1", "year": 2026, "value": 1}],
        )
    population_without_lineage = _population_artifact()
    population_without_lineage["records"][0]["sourceIds"] = []
    with pytest.raises(ValueError, match="population.*source ID"):
        build_regional_demand_weights(
            population_artifact=population_without_lineage,
            active_geography_ids={"AA-1", "AA-2"},
        )


def test_weight_builder_cli_is_deterministic(tmp_path: Path) -> None:
    population = tmp_path / "population.json"
    population.write_text(json.dumps(_population_artifact()))
    boundaries = tmp_path / "boundaries.geojson"
    boundaries.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "AA-2", "properties": {"id": "AA-2"}, "geometry": None},
        {"type": "Feature", "id": "AA-1", "properties": {"id": "AA-1"}, "geometry": None},
    ]}))
    activity = tmp_path / "activity.csv"
    activity.write_text(
        "geographyId,year,activityShare,sourceId\n"
        "AA-2,2026,0.7,public-lights\n"
        "AA-1,2026,0.3,public-lights\n"
    )
    official = tmp_path / "official.csv"
    official.write_text(
        "geographyId,country,year,source_ids,method_id,value_kind\n"
        "AA-1,AA,2026,official-aa,official-direct-v1,reported\n"
    )
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    command = [
        sys.executable, "scripts/build-regional-demand-weights.py",
        "--population", str(population), "--boundaries", str(boundaries),
        "--activity", str(activity), "--official-observations", str(official), "--output",
    ]
    root = Path(__file__).parents[2]
    for output in (first, second):
        completed = subprocess.run([*command, str(output)], cwd=root, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text())
    assert payload["buildInputs"]["populationFingerprint"] == "sha256:population"
    row = next(item for item in payload["records"] if item["geographyId"] == "AA-1" and item["year"] == 2026)
    assert row["activityShare"] == pytest.approx(0.3)
    assert payload["officialObservationLineage"][0]["sourceIds"] == ["official-aa"]
