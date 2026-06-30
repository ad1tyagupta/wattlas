from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping

import httpx

from grid_scope.config import (
    CURATED_PATH,
    GLOBAL_ADMIN1_PATH,
    GLOBAL_ASSETS_PATH,
    MODEL_VERSION,
    PUBLISH_DIR,
    QLEVER_OSM_URL,
    RAW_DIR,
    SOURCE_REGISTRY_PATH,
    UN_GEODATA_URL,
    WAREHOUSE_PATH,
)
from grid_scope.canonicalize import assign_asset_country, canonicalize_assets
from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.connectors.curated import CuratedConnector
from grid_scope.connectors.entsoe import EntsoeConnector
from grid_scope.connectors.ember import normalize_ember_yearly_csv
from grid_scope.connectors.eurostat import EurostatConnector, parse_population
from grid_scope.connectors.gisco import GiscoConnector
from grid_scope.connectors.global_assets import load_asset_registry
from grid_scope.connectors.gem_power import GemPowerConnector
from grid_scope.connectors.osm_infrastructure import OSM_SOURCE_ID, OsmInfrastructureConnector
from grid_scope.connectors.osm_power import OsmPowerConnector
from grid_scope.connectors.regional_electricity import (
    load_curated_regional_observations,
    merge_regional_observations,
)
from grid_scope.connectors.un_geodata import UnGeodataConnector
from grid_scope.connectors.wri_power import WriPowerConnector
from grid_scope.models import ConnectorState
from grid_scope.population import load_population_artifact
from grid_scope.power_balance import (
    build_regional_energy_forecasts,
    load_generation_assumptions,
)
from grid_scope.power_plants import canonicalize_power_plants
from grid_scope.regional_demand import allocate_country_demand, load_regional_demand_methods
from grid_scope.scoring import score_power_balance
from grid_scope.publisher import SnapshotPublisher
from grid_scope.snapshot_builder import build_global_snapshot_artifacts, build_snapshot_artifacts
from grid_scope.storage import RawCaptureStore


POWER_SOURCE_PRECEDENCE = (
    "official_power",
    "gem_power",
    "wri_power",
    "osm_power",
)
REFRESH_STEPS = (
    "boundaries",
    "population",
    "plant_sources",
    "plant_canonicalization",
    "country_electricity_controls",
    "official_adm1_observations",
    "modelled_adm1_residual_demand",
    "supply_balance_forecast",
    "scores",
    "artifacts",
    "validation",
    "atomic_publish",
)
_FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_QUALITY_COUNT_FIELDS = (
    "countries",
    "admin1Regions",
    "canonicalPowerPlants",
    "canonicalPowerUnits",
    "generatorRegions",
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _validated_fingerprint(value: object, *, label: str) -> str:
    if value == "sha256:unbuilt":
        raise ValueError(f"{label} is unbuilt")
    if not isinstance(value, str) or _FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a versioned SHA-256 fingerprint")
    return value


def load_refresh_model_artifacts(
    population_path: Path,
    demand_weights_path: Path,
    *,
    validate_population: bool = True,
) -> dict[str, dict[str, Any]]:
    """Load compact, versioned model inputs; daily refresh never opens a raster."""

    population = (
        load_population_artifact(population_path)
        if validate_population
        else _read_json(population_path)
    )
    weights = _read_json(demand_weights_path)
    if population.get("schemaVersion") != "wattlas-adm1-population-v1":
        raise ValueError("unsupported ADM1 population artifact")
    if weights.get("schemaVersion") != "wattlas-regional-demand-weights-v1":
        raise ValueError("unsupported regional demand weights artifact")
    _validated_fingerprint(population.get("buildFingerprint"), label="population artifact")
    _validated_fingerprint(weights.get("buildFingerprint"), label="demand weights artifact")
    _validated_fingerprint(
        weights.get("effectiveInputFingerprint"), label="demand weights effective inputs"
    )
    weight_inputs = weights.get("buildInputs")
    if not isinstance(weight_inputs, Mapping):
        raise ValueError("regional demand weights require versioned build inputs")
    population_fingerprint = _validated_fingerprint(
        weight_inputs.get("populationFingerprint"),
        label="demand weights population release",
    )
    if population_fingerprint != population.get("buildFingerprint"):
        raise ValueError("demand weights do not match the population release")
    records = weights.get("records")
    if not isinstance(records, list):
        raise ValueError("regional demand weights require a records array")
    return {"population": population, "demandWeights": weights}


def _source_observation_date(body: bytes | None) -> str | None:
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    candidates: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key in ("observationDate", "updatedAt", "updated_at"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    candidates.append(candidate.strip()[:10])
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(payload)
    return max(candidates) if candidates else None


def build_connector_status(
    result: ConnectorResult,
    *,
    checked_at: str,
    observation_body: bytes | None = None,
    last_success_at: str | None = None,
) -> dict[str, object]:
    body = observation_body
    if body is None and result.payload is not None:
        body = result.payload.body
    return {
        "id": result.source_id,
        "state": result.state.value,
        # Daily means checked today. It never rewrites upstream observation dates.
        "checkedAt": checked_at,
        "lastSuccessAt": (
            checked_at if result.state == ConnectorState.CURRENT else last_success_at
        ),
        "observationDate": _source_observation_date(body),
        "message": result.message,
    }


def validate_refresh_quality(
    current_manifest: Mapping[str, Any],
    previous_manifest: Mapping[str, Any] | None = None,
) -> None:
    coverage = current_manifest.get("coverage")
    if not isinstance(coverage, Mapping):
        raise ValueError("refresh coverage report is missing")
    quality = current_manifest.get("quality")
    if not isinstance(quality, Mapping):
        raise ValueError("refresh quality report is missing")
    if not quality.get("countryDemandReconciled") or not quality.get(
        "generatorArtifactsReconciled"
    ):
        raise ValueError("refresh reconciliation failed")
    for field in ("powerSourceRecords", "canonicalPowerPlants", "canonicalPowerUnits"):
        value = coverage.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"invalid refresh coverage count: {field}")
    if previous_manifest is None:
        return
    previous = previous_manifest.get("coverage")
    if not isinstance(previous, Mapping):
        return
    for field in _QUALITY_COUNT_FIELDS:
        old = previous.get(field)
        new = coverage.get(field)
        if (
            isinstance(old, int) and not isinstance(old, bool) and old > 0
            and isinstance(new, int) and not isinstance(new, bool) and new < old
        ):
            raise ValueError(f"coverage drop for {field}: {new} < {old}")


def _network_result(
    fetch: Callable[[], ConnectorResult],
    source_id: str,
    store: RawCaptureStore,
) -> tuple[bytes, ConnectorResult]:
    try:
        result = fetch()
        if result.payload:
            capture = store.save(
                result.source_id,
                result.payload.body,
                result.payload.media_type,
            )
            return capture.path.read_bytes(), result
        raise RuntimeError(result.message or f"{source_id} returned no payload")
    except Exception as error:
        previous = store.latest_capture(source_id)
        if previous:
            return previous.path.read_bytes(), ConnectorResult(
                source_id=source_id,
                state=ConnectorState.CACHED,
                payload=None,
                message=f"Using last successful capture: {error}",
            )
        raise


def _optional_network_result(
    fetch: Callable[[], ConnectorResult],
    source_id: str,
    store: RawCaptureStore,
) -> tuple[bytes, ConnectorResult]:
    """Fetch one optional public source without borrowing another source's cache."""

    try:
        result = fetch()
        if result.payload is not None and result.payload.body:
            capture = store.save(
                result.source_id, result.payload.body, result.payload.media_type
            )
            return capture.path.read_bytes(), result
        previous = store.latest_capture(source_id)
        if previous is not None:
            return previous.path.read_bytes(), ConnectorResult(
                source_id=source_id,
                state=ConnectorState.CACHED,
                payload=None,
                message=(
                    f"Using last successful capture: {result.message or 'source returned no payload'}"
                ),
            )
        if result.state == ConnectorState.NOT_CONFIGURED:
            return b'{"records":[]}', result
        raise RuntimeError(result.message or f"{source_id} returned no payload")
    except Exception as error:
        previous = store.latest_capture(source_id)
        if previous is not None:
            return previous.path.read_bytes(), ConnectorResult(
                source_id=source_id,
                state=ConnectorState.CACHED,
                payload=None,
                message=f"Using last successful capture: {error}",
            )
        raise


def collect_power_source_records(
    payloads: Mapping[str, bytes],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Materialize power records in explicit official/GEM/WRI/OSM precedence."""

    records: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for source_id in POWER_SOURCE_PRECEDENCE:
        body = payloads.get(source_id, b'{"records":[]}')
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"{source_id} capture is not valid JSON") from error
        source_records = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(source_records, list) or any(
            not isinstance(record, dict) for record in source_records
        ):
            raise ValueError(f"{source_id} capture requires a records array")
        counts[source_id] = len(source_records)
        records.extend(dict(record) for record in source_records)
    return records, counts


def _local_json_source(
    path: Path | None,
    *,
    source_id: str,
    now: datetime,
) -> ConnectorResult:
    if path is None:
        return ConnectorResult(
            source_id=source_id,
            state=ConnectorState.NOT_CONFIGURED,
            payload=None,
            message=f"Optional {source_id} public release is not configured.",
        )
    body = path.read_bytes()
    payload = json.loads(body)
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise ValueError(f"{source_id} release requires a records array")
    return ConnectorResult(
        source_id=source_id,
        state=ConnectorState.CURRENT,
        payload=FetchPayload(
            source_id=source_id,
            retrieved_at=now,
            media_type="application/json",
            body=body,
        ),
    )


def _records_result(
    records: list[dict[str, Any]],
    *,
    source_id: str,
    now: datetime,
    configured: bool,
) -> ConnectorResult:
    if not configured:
        return ConnectorResult(
            source_id=source_id,
            state=ConnectorState.NOT_CONFIGURED,
            payload=None,
            message=f"Optional {source_id} public source is not configured.",
        )
    return ConnectorResult(
        source_id=source_id,
        state=ConnectorState.CURRENT,
        payload=FetchPayload(
            source_id=source_id,
            retrieved_at=now,
            media_type="application/json",
            body=json.dumps(
                {"records": records}, separators=(",", ":"), ensure_ascii=False
            ).encode(),
        ),
    )


def _clamp_index(value: float) -> float:
    return max(0.0, min(100.0, value))


def _attach_power_balance_scores(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    first_demand = float(rows[0]["metrics"]["demandGwh"]["central"])
    for row in rows:
        metrics = row["metrics"]
        demand = float(metrics["demandGwh"]["central"])
        peak = float(metrics["peakDemandMw"]["central"])
        dependable = metrics.get("dependableCapacityMw")
        local_gap = metrics.get("localGenerationGapGwh")
        unmet = metrics.get("observedUnmetDemandGwh")
        capacity_pressure = (
            _clamp_index(100 - 100 * float(dependable["central"]) / peak)
            if dependable is not None and peak > 0 else None
        )
        local_pressure = (
            _clamp_index(100 * max(0.0, float(local_gap["central"])) / demand)
            if local_gap is not None and demand > 0 else None
        )
        unmet_pressure = (
            _clamp_index(100 * float(unmet) / demand)
            if unmet is not None and demand > 0 else None
        )
        growth_pressure = (
            _clamp_index(100 * max(0.0, demand - first_demand) / first_demand)
            if first_demand > 0 else None
        )
        # Delivery pressure stays unavailable unless the supply model publishes
        # a distinct delivery metric; absence must never be converted to zero.
        result = score_power_balance(
            capacity_margin_index=capacity_pressure,
            local_balance_index=local_pressure,
            observed_unmet_demand_index=unmet_pressure,
            demand_growth_index=growth_pressure,
            supply_delivery_index=None,
            source_ids=row["sourceIds"],
            value_kinds={
                "capacity_margin": "estimated" if capacity_pressure is not None else "unavailable",
                "annual_local_balance": "estimated" if local_pressure is not None else "unavailable",
                "observed_unmet_demand": "reported" if unmet_pressure is not None else "unavailable",
                "forecast_demand_growth": "estimated" if growth_pressure is not None else "unavailable",
                "supply_delivery_gap": "unavailable",
            },
        )
        row["powerBalance"] = {
            "score": result.score,
            "coverage": result.coverage,
            "status": result.status,
            "contributions": [
                contribution.model_dump(by_alias=True, mode="json")
                for contribution in result.contributions
            ],
        }


def build_regional_energy_model(
    *,
    demand_weights: Mapping[str, Any],
    country_controls: Iterable[Mapping[str, Any]],
    official_observations: Iterable[Mapping[str, Any]],
    power_records: Iterable[Mapping[str, Any]],
    assumptions: Mapping[str, Any],
    method_config: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    """Build country-controlled ADM1 residual demand, then supply and balance."""

    weights = [dict(row) for row in demand_weights.get("records", [])]
    controls = [dict(row) for row in country_controls if row.get("demandGwh") is not None]
    official = [dict(row) for row in official_observations]
    if not weights or not controls:
        return {}, True
    latest_controls: dict[str, dict[str, Any]] = {}
    for control in controls:
        country = str(control.get("countryIso3") or "").strip().upper()
        if country and (
            country not in latest_controls
            or int(control["year"]) > int(latest_controls[country]["year"])
        ):
            latest_controls[country] = control
    demand_by_region: dict[str, list[dict[str, Any]]] = {}
    reconciled = True
    for country, control in sorted(latest_controls.items()):
        for year in range(2026, 2032):
            year_weights = [
                row for row in weights
                if str(row.get("countryIso3") or "").upper() == country
                and int(row.get("year", 0)) == year
            ]
            if not year_weights:
                continue
            projected_control = {
                **control,
                "year": year,
                "valueKind": "inherited" if int(control["year"]) != year else control.get("valueKind", "reported"),
                "methodId": (
                    str(control.get("methodId") or "country-control")
                    if int(control["year"]) == year
                    else "latest-country-control-flat-baseline-v1"
                ),
            }
            allocated = allocate_country_demand(
                regions=year_weights,
                country_control=projected_control,
                official_observations=[
                    row for row in official
                    if str(row.get("countryIso3") or "").upper() == country
                    and int(row.get("year", 0)) == year
                    and row.get("demandGwh") is not None
                    and row.get("geographyId") in {
                        item.get("geographyId") for item in year_weights
                    }
                ],
                as_of_year=year,
                covariate_year=year,
                method_config=method_config,
            )
            expected = float(projected_control["demandGwh"] if not isinstance(projected_control["demandGwh"], Mapping) else projected_control["demandGwh"]["central"])
            actual = sum(float(row["demandGwh"]["central"]) for row in allocated)
            reconciled = reconciled and abs(actual - expected) <= max(1e-6, abs(expected) * 1e-6)
            for row in allocated:
                demand_by_region.setdefault(row["geographyId"], []).append(row)
    plants = [dict(row) for row in power_records]
    forecasts: dict[str, list[dict[str, Any]]] = {}
    for region_id, rows in sorted(demand_by_region.items()):
        if [row["year"] for row in rows] != list(range(2026, 2032)):
            continue
        net_interchange: dict[int, object] = {}
        observed_unmet: dict[int, object] = {}
        for observation in official:
            if observation.get("geographyId") != region_id:
                continue
            year = int(observation["year"])
            provenance = {
                "sourceIds": observation.get("sourceIds") or [observation.get("sourceId")],
                "methodId": observation.get("methodId"),
                "valueKind": observation.get("valueKind"),
            }
            if observation.get("netInterchangeGwh") is not None:
                net_interchange[year] = {**provenance, "netInterchangeGwh": observation["netInterchangeGwh"]}
            if observation.get("observedUnmetDemandGwh") is not None:
                observed_unmet[year] = {**provenance, "observedUnmetDemandGwh": observation["observedUnmetDemandGwh"]}
        regional = build_regional_energy_forecasts(
            geography_id=region_id,
            demand_forecasts=rows,
            plants=plants,
            assumptions=assumptions,
            net_interchange_by_year=net_interchange,
            observed_unmet_by_year=observed_unmet,
        )
        _attach_power_balance_scores(regional)
        forecasts[region_id] = regional
    return forecasts, reconciled


def merge_asset_feeds(
    countries: dict,
    official_registry: dict,
    osm_payload: dict,
    *,
    observed_at: str,
) -> dict:
    country_features = countries.get("features", [])
    community_assets: list[dict] = []
    for source_asset in osm_payload.get("assets", []):
        asset = dict(source_asset)
        country = assign_asset_country(asset, country_features)
        if not country:
            continue
        asset["country"] = country
        if asset.get("geographyId") == "UNASSIGNED":
            asset["geographyId"] = country
        community_assets.append(asset)

    sources = list(official_registry.get("sources", []))
    if not any(source.get("id") == OSM_SOURCE_ID for source in sources):
        sources.append({
            "id": OSM_SOURCE_ID,
            "name": "OpenStreetMap infrastructure mapping",
            "tier": "C",
            "url": "https://www.openstreetmap.org/copyright",
            "publishedAt": observed_at,
        })
    return {
        **official_registry,
        "sources": sources,
        "assets": canonicalize_assets([
            *community_assets,
            *official_registry.get("assets", []),
        ]),
    }


def refresh() -> Path:
    now = datetime.now(UTC).replace(microsecond=0)
    generated_at = now.isoformat().replace("+00:00", "Z")
    snapshot_id = generated_at.replace(":", "-")
    store = RawCaptureStore(RAW_DIR, WAREHOUSE_PATH)
    source_bodies: dict[str, bytes] = {}

    with httpx.Client(timeout=90, follow_redirects=True) as client:
        countries_body, countries_status = _network_result(
            lambda: UnGeodataConnector(UN_GEODATA_URL).fetch(client, now=now),
            "un_geodata",
            store,
        )
        gisco_body, gisco_status = _network_result(
            lambda: GiscoConnector().fetch(client, now=now), "gisco", store
        )
        eurostat_body, eurostat_status = _network_result(
            lambda: EurostatConnector().fetch(client, now=now), "eurostat", store
        )
        osm_body, osm_status = _network_result(
            lambda: OsmInfrastructureConnector(QLEVER_OSM_URL).fetch(client, now=now),
            "osm_infrastructure",
            store,
        )
        gem_body, gem_status = _optional_network_result(
            lambda: GemPowerConnector().fetch(client, now=now), "gem_power", store
        )
        wri_body, wri_status = _optional_network_result(
            lambda: WriPowerConnector().fetch(client, now=now), "wri_power", store
        )
        osm_power_body, osm_power_status = _optional_network_result(
            lambda: OsmPowerConnector(QLEVER_OSM_URL).fetch(client, now=now),
            "osm_power",
            store,
        )

    official_power_path_value = os.getenv("OFFICIAL_POWER_PATH")
    official_power_path = Path(official_power_path_value) if official_power_path_value else None
    official_power_body, official_power_status = _optional_network_result(
        lambda: _local_json_source(
            official_power_path, source_id="official_power", now=now
        ),
        "official_power",
        store,
    )
    source_bodies.update({
        "official_power": official_power_body,
        "gem_power": gem_body,
        "wri_power": wri_body,
        "osm_power": osm_power_body,
    })

    curated_result = CuratedConnector(CURATED_PATH).fetch(now=now)
    assert curated_result.payload is not None
    store.save(
        curated_result.source_id,
        curated_result.payload.body,
        curated_result.payload.media_type,
    )
    entsoe_status = EntsoeConnector(os.getenv("ENTSOE_SECURITY_TOKEN")).fetch(now=now)

    global_assets_result = CuratedConnector(
        GLOBAL_ASSETS_PATH, source_id="global_assets"
    ).fetch(now=now)
    source_registry_result = CuratedConnector(
        SOURCE_REGISTRY_PATH, source_id="source_registry"
    ).fetch(now=now)
    global_admin1_result = CuratedConnector(
        GLOBAL_ADMIN1_PATH, source_id="geoboundaries_adm1"
    ).fetch(now=now)
    for result in (global_assets_result, source_registry_result, global_admin1_result):
        assert result.payload is not None
        store.save(result.source_id, result.payload.body, result.payload.media_type)

    geometry = json.loads(gisco_body)
    population = parse_population(json.loads(eurostat_body))
    curated = json.loads(curated_result.payload.body)
    europe_artifacts = build_snapshot_artifacts(geometry, population, curated, generated_at)
    registry = load_asset_registry(GLOBAL_ASSETS_PATH, SOURCE_REGISTRY_PATH)
    countries = json.loads(countries_body)
    registry = merge_asset_feeds(
        countries,
        registry,
        json.loads(osm_body),
        observed_at=generated_at,
    )
    registry["modelNote"] = json.loads(GLOBAL_ASSETS_PATH.read_text()).get("modelNote")
    store.save_canonical_assets(registry["assets"])

    admin1_payload = json.loads(global_admin1_result.payload.body)
    population_path = Path(
        os.getenv(
            "ADM1_POPULATION_ARTIFACT_PATH",
            str(CURATED_PATH.parent / "admin1-population.json"),
        )
    )
    weights_path = Path(
        os.getenv(
            "REGIONAL_DEMAND_WEIGHTS_PATH",
            str(CURATED_PATH.parent / "regional-demand-weights.json"),
        )
    )
    model_artifacts: dict[str, dict[str, Any]] | None = None
    if population_path.exists() and weights_path.exists():
        model_artifacts = load_refresh_model_artifacts(population_path, weights_path)

    power_source_records, power_source_counts = collect_power_source_records(source_bodies)
    canonical_power = canonicalize_power_plants(
        power_source_records,
        geographies=admin1_payload.get("features", []),
    )
    active_admin1 = {
        str((feature.get("properties") or {}).get("id") or feature.get("id") or "").strip()
        for feature in admin1_payload.get("features", [])
    }
    country_iso3 = {
        str((feature.get("properties") or {}).get("id") or feature.get("id") or "").strip():
        str((feature.get("properties") or {}).get("iso3") or "").strip().upper()
        for feature in countries.get("features", [])
    }
    admin1_country = {
        str((feature.get("properties") or {}).get("id") or feature.get("id") or "").strip():
        str((feature.get("properties") or {}).get("country") or "").strip().upper()
        for feature in admin1_payload.get("features", [])
    }
    publishable_plants = [
        plant for plant in canonical_power["plants"]
        if plant.get("geographyId") in active_admin1
        and admin1_country.get(str(plant.get("geographyId"))) == str(plant.get("country") or "").upper()
        and plant.get("coordinates") is not None
    ]

    ember_path_value = os.getenv("EMBER_YEARLY_PATH")
    country_controls = (
        normalize_ember_yearly_csv(Path(ember_path_value)) if ember_path_value else []
    )
    country_control_status = _records_result(
        country_controls,
        source_id="country_electricity_controls",
        now=now,
        configured=bool(ember_path_value),
    )
    if country_control_status.payload is not None:
        store.save(
            country_control_status.source_id,
            country_control_status.payload.body,
            country_control_status.payload.media_type,
        )
    official_observations: list[dict[str, Any]] = []
    observed_path_value = os.getenv(
        "REGIONAL_ELECTRICITY_OBSERVED_PATH",
        str(CURATED_PATH.parent / "regional-electricity-observed.csv"),
    )
    observed_path = Path(observed_path_value)
    if observed_path.exists() and observed_path.stat().st_size > 0:
        with observed_path.open(encoding="utf-8-sig") as source:
            has_records = sum(1 for _ in source) > 1
        if has_records:
            identity_mapping = {region_id: region_id for region_id in active_admin1}
            official_observations = merge_regional_observations(
                load_curated_regional_observations(
                    observed_path,
                    region_mapping=identity_mapping,
                    active_geography_ids=active_admin1,
                    geography_country_iso3={
                        region_id: country_iso3.get(country, country)
                        for region_id, country in admin1_country.items()
                    },
                )
            )
    official_regional_status = _records_result(
        official_observations,
        source_id="official_adm1_electricity",
        now=now,
        configured=observed_path.exists(),
    )
    if official_regional_status.payload is not None:
        store.save(
            official_regional_status.source_id,
            official_regional_status.payload.body,
            official_regional_status.payload.media_type,
        )
    regional_energy: dict[str, list[dict[str, Any]]] = {}
    country_demand_reconciled = True
    if model_artifacts is not None:
        forecast_power_records = [
            {
                **record,
                "targetYear": (
                    record.get("targetYear")
                    or record.get("expectedCommissioningYear")
                ),
            }
            for record in canonical_power["records"]
        ]
        regional_energy, country_demand_reconciled = build_regional_energy_model(
            demand_weights=model_artifacts["demandWeights"],
            country_controls=country_controls,
            official_observations=official_observations,
            power_records=forecast_power_records,
            assumptions=load_generation_assumptions(
                CURATED_PATH.parent / "generation-assumptions.json"
            ),
            method_config=load_regional_demand_methods(
                CURATED_PATH.parent / "regional-demand-methods.json"
            ),
        )
    artifacts = build_global_snapshot_artifacts(
        countries=countries,
        admin1=admin1_payload,
        regions=json.loads(europe_artifacts["regions.geojson"]),
        registry=registry,
        generated_at=generated_at,
        regional_energy=regional_energy,
        power_plants=publishable_plants,
        population_records=(
            model_artifacts["population"].get("records", [])
            if model_artifacts is not None else []
        ),
    )

    statuses = [
        countries_status,
        gisco_status,
        eurostat_status,
        osm_status,
        global_assets_result,
        source_registry_result,
        global_admin1_result,
        curated_result,
        entsoe_status,
        official_power_status,
        gem_status,
        wri_status,
        osm_power_status,
        country_control_status,
        official_regional_status,
    ]
    country_count = len(json.loads(artifacts["countries.geojson"])["features"])
    asset_features = json.loads(artifacts["assets.geojson"])["features"]
    manifest = {
        "snapshotId": snapshot_id,
        "generatedAt": generated_at,
        "modelVersion": MODEL_VERSION,
        "activeYears": [2026, 2027, 2028, 2029, 2030, 2031],
        "artifacts": {
            "countries": f"snapshots/{snapshot_id}/countries.geojson",
            "admin1": f"snapshots/{snapshot_id}/admin1.geojson",
            "regions": f"snapshots/{snapshot_id}/regions.geojson",
            "assets": f"snapshots/{snapshot_id}/assets.geojson",
            "evidence": f"snapshots/{snapshot_id}/evidence.json",
            "regionalEnergy": f"snapshots/{snapshot_id}/regional-energy.json",
            "generatorOverview": f"snapshots/{snapshot_id}/generator-overview.geojson",
            "generatorIndex": f"snapshots/{snapshot_id}/generators/index.json",
        },
        "coverage": {
            "countries": country_count,
            "regions": len(json.loads(artifacts["regions.geojson"])["features"]),
            "admin1Regions": len(json.loads(artifacts["admin1.geojson"])["features"]),
            "countriesWithAdmin1": len({
                feature["properties"]["country"]
                for feature in json.loads(artifacts["admin1.geojson"])["features"]
            }),
            "assets": len(asset_features),
            "dataCentres": sum(feature["properties"]["category"] == "data_centre" for feature in asset_features),
            "waterInfrastructure": sum(feature["properties"]["category"] == "water_infrastructure" for feature in asset_features),
            "powerSourceRecords": len(power_source_records),
            "powerSourceRecordsBySource": power_source_counts,
            "canonicalPowerPlants": len(canonical_power["plants"]),
            "canonicalPowerUnits": len(canonical_power["units"]),
            "publishedPowerPlants": len(publishable_plants),
            "generatorRegions": len(json.loads(artifacts["generator-overview.geojson"])["features"]),
            "regionalEnergyRegions": len(regional_energy),
        },
        "quality": {
            "countryDemandReconciled": country_demand_reconciled,
            "generatorArtifactsReconciled": True,
            "populationBuildFingerprint": (
                model_artifacts["population"].get("buildFingerprint")
                if model_artifacts is not None else None
            ),
            "demandWeightsBuildFingerprint": (
                model_artifacts["demandWeights"].get("buildFingerprint")
                if model_artifacts is not None else None
            ),
        },
        "boundaryDisclaimer": json.loads(artifacts["countries.geojson"]).get("metadata", {}).get("disclaimer"),
        "connectors": [],
    }
    body_by_source = {
        "un_geodata": countries_body,
        "gisco": gisco_body,
        "eurostat": eurostat_body,
        "osm_infrastructure": osm_body,
        **source_bodies,
        "country_electricity_controls": (
            country_control_status.payload.body
            if country_control_status.payload is not None else b""
        ),
        "official_adm1_electricity": (
            official_regional_status.payload.body
            if official_regional_status.payload is not None else b""
        ),
    }
    for result in statuses:
        previous_capture = store.latest_capture(result.source_id)
        last_success = (
            previous_capture.retrieved_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if previous_capture is not None else None
        )
        manifest["connectors"].append(build_connector_status(
            result,
            checked_at=generated_at,
            observation_body=body_by_source.get(result.source_id),
            last_success_at=last_success,
        ))
    latest_path = PUBLISH_DIR / "latest.json"
    previous_manifest = _read_json(latest_path) if latest_path.exists() else None
    validate_refresh_quality(manifest, previous_manifest)
    return SnapshotPublisher(PUBLISH_DIR).publish(snapshot_id, artifacts, manifest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Wattlas daily snapshot from public sources."
    )
    parser.add_argument("command", nargs="?", choices=["refresh"], default="refresh")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    path = refresh()
    print(f"Published daily snapshot: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
