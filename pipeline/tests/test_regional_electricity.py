from __future__ import annotations

import csv
from datetime import UTC, datetime
import json
from pathlib import Path

import httpx
import pytest

from grid_scope.connectors.eia import EiaV2Connector, normalize_eia_state
from grid_scope.connectors.ember import normalize_ember_yearly_csv
from grid_scope.connectors.regional_electricity import (
    load_curated_regional_observations,
    merge_regional_observations,
    normalize_metric_value,
    validate_region_mapping,
)
from grid_scope.models import ConnectorState


FIXTURES = Path(__file__).parent / "fixtures"


def test_ember_yearly_country_controls_keep_period_metric_units_and_mix() -> None:
    records = normalize_ember_yearly_csv(FIXTURES / "ember-yearly-sample.csv")

    usa = next(record for record in records if record["countryIso3"] == "USA")
    assert usa["geographyLevel"] == "country"
    assert usa["geographyId"] == "USA"
    assert usa["year"] == 2024
    assert usa["period"] == "annual"
    assert usa["demandGwh"] == 4_120_500
    assert usa["localGenerationGwh"] == 4_380_000
    assert usa["generationMixGwh"] == {"solar": 303_200, "wind": 453_500}
    assert usa["sourceIds"] == ["ember-yearly-electricity-data"]
    assert usa["sourceUrl"].startswith("https://")
    assert usa["licence"] == "CC-BY-4.0"
    assert usa["observationDate"] == "2024-12-31"
    assert usa["updatedAt"] == "2026-05-01"
    assert usa["freshnessDays"] == 486
    assert usa["valueKind"] == "reported"
    assert usa["methodId"] == "ember-yearly-v1"
    assert usa["unitMetadata"]["demandGwh"]["sourceUnit"] == "TWh"

    france = next(record for record in records if record["countryIso3"] == "FRA")
    assert france["demandGwh"] is None
    assert france["localGenerationGwh"] is None
    assert france["generationMixGwh"] == {}


def test_country_controls_cannot_be_merged_as_adm1_observations() -> None:
    country = normalize_ember_yearly_csv(FIXTURES / "ember-yearly-sample.csv")[0]
    with pytest.raises(ValueError, match="ADM1"):
        merge_regional_observations([country])


def test_eia_state_balance_keeps_interchange_and_unknown_unmet_demand_separate() -> None:
    payloads = json.loads((FIXTURES / "eia-state-sample.json").read_text())
    normalized = []
    for route_id, payload in payloads.items():
        normalized.extend(normalize_eia_state(
            payload,
            route_id=route_id,
            state_mapping={"TX": "US-TEXAS"},
            active_geography_ids={"US-TEXAS"},
            balancing_authority_mapping={"ERCO": "US-TEXAS"},
            source_url="https://api.eia.gov/v2/electricity/",
            retrieved_at="2026-06-28",
        ))
    records = merge_regional_observations(normalized)

    assert len(records) == 1
    record = records[0]
    assert record["geographyId"] == "US-TEXAS"
    assert record["countryIso3"] == "USA"
    assert record["demandGwh"] == 82_400
    assert record["localGenerationGwh"] == 75_000
    assert record["netInterchangeGwh"] == 7_700
    assert record["observedUnmetDemandGwh"] is None
    assert record["installedCapacityMw"] is None
    assert record["dependableCapacityMw"] == 152_000
    assert record["peakDemandMw"] is None
    assert record["generationMixGwh"] == {"gas": 20_000, "solar": 15_000}
    assert record["fieldProvenance"]["netInterchangeGwh"]["sourceSeries"]["facet"] == "ERCO"
    assert record["fieldProvenance"]["demandGwh"]["sourceSeries"]["routeId"] == "sales"
    assert record["fieldProvenance"]["localGenerationGwh"]["sourceSeries"]["facet"] == "TX"
    assert record["fieldProvenance"]["localGenerationGwh"]["sourceSeries"]["apiVersion"] == "2.1.0"
    assert record["fieldProvenance"]["dependableCapacityMw"]["sourceSeries"]["routeId"] == "capability"
    assert record["sourceIds"] == ["eia-api-v2"]
    assert record["licence"] == "US-PUBLIC-DOMAIN"
    assert record["freshnessDays"] == 544


def test_eia_balancing_authority_interchange_is_not_guessed_from_state() -> None:
    payload = json.loads((FIXTURES / "eia-state-sample.json").read_text())["interchange"]
    report: dict = {}
    records = normalize_eia_state(
        payload,
        route_id="interchange",
        state_mapping={"TX": "US-TEXAS"},
        active_geography_ids={"US-TEXAS"},
        source_url="https://api.eia.gov/v2/electricity/",
        report=report,
    )
    assert records == []
    assert report["unmappedBalancingAuthorities"] == ["ERCO"]


def test_eia_real_units_are_exact_and_incompatible_hourly_power_is_rejected() -> None:
    assert normalize_metric_value(
        "82", unit="Million kilowatt-hours", dimension="energy"
    ) == 82
    assert normalize_metric_value(
        "82", unit="million kilowatthours", dimension="energy"
    ) == 82
    assert normalize_metric_value(
        "75", unit="thousand megawatt hours", dimension="energy"
    ) == 75
    assert normalize_metric_value("152", unit="megawatts", dimension="power") == 152

    hourly = {
        "apiVersion": "2.1.0",
        "response": {
            "frequency": "hourly",
            "dateFormat": "YYYY-MM-DDTHH24",
            "data": [{
                "period": "2024-01-01T00", "respondent": "ERCO", "type": "TI",
                "value": "100", "value-units": "megawatts",
            }],
        },
    }
    with pytest.raises(ValueError, match="annual.*energy|hourly"):
        normalize_eia_state(
            hourly,
            route_id="interchange",
            state_mapping={"TX": "US-TEXAS"},
            active_geography_ids={"US-TEXAS"},
            balancing_authority_mapping={"ERCO": "US-TEXAS"},
        )


def test_eia_generation_location_requires_an_explicit_active_mapping() -> None:
    generation = json.loads((FIXTURES / "eia-state-sample.json").read_text())["generation"]
    with pytest.raises(ValueError, match="unmapped source region codes.*TX"):
        normalize_eia_state(
            generation,
            route_id="generation",
            state_mapping={"CA": "US-CALIFORNIA"},
            active_geography_ids={"US-CALIFORNIA"},
        )


def test_eia_generation_mix_drops_overlapping_fuel_hierarchy_aggregates() -> None:
    payload = json.loads(
        (FIXTURES / "eia-generation-hierarchy-sample.json").read_text()
    )
    record = normalize_eia_state(
        payload,
        route_id="generation",
        state_mapping={"TX": "US-TEXAS"},
        active_geography_ids={"US-TEXAS"},
    )[0]

    assert record["localGenerationGwh"] == 100
    assert record["generationMixGwh"] == {
        "biomass": 5,
        "coal": 40,
        "gas": 20,
        "hydro": 5,
        "oil": 10,
        "solar": 10,
        "wind": 10,
    }
    coal_lineage = record["sourceSeries"]["generationMixGwh.coal"]["aggregatedFacets"]
    assert {item["rawFuelCode"] for item in coal_lineage} == {"BIT", "SUB"}
    biomass_lineage = record["sourceSeries"]["generationMixGwh.biomass"][
        "aggregatedFacets"
    ]
    assert {item["rawFuelCode"] for item in biomass_lineage} == {"WDL", "WDS"}


def test_eia_generation_mix_rejects_selected_components_above_all_fuel_total() -> None:
    payload = {
        "response": {
            "frequency": "annual",
            "data": [
                {"period": "2024", "location": "TX", "sectorid": "ALL",
                 "fueltypeid": "ALL", "generation": "10",
                 "generation-units": "thousand megawatthours"},
                {"period": "2024", "location": "TX", "sectorid": "ALL",
                 "fueltypeid": "NG", "generation": "11",
                 "generation-units": "thousand megawatthours"},
            ],
        },
    }
    with pytest.raises(ValueError, match="generation mix.*exceeds.*total"):
        normalize_eia_state(
            payload,
            route_id="generation",
            state_mapping={"TX": "US-TEXAS"},
            active_geography_ids={"US-TEXAS"},
        )


def test_eia_generation_aggregate_is_kept_only_as_fallback_without_descendants() -> None:
    payload = {
        "response": {
            "frequency": "annual",
            "data": [{
                "period": "2024", "location": "TX", "sectorid": "ALL",
                "fueltypeid": "FOS", "generation": "9",
                "generation-units": "thousand megawatthours",
            }],
        },
    }
    record = normalize_eia_state(
        payload,
        route_id="generation",
        state_mapping={"TX": "US-TEXAS"},
        active_geography_ids={"US-TEXAS"},
    )[0]
    assert record["generationMixGwh"] == {"other": 9}
    assert record["sourceSeries"]["generationMixGwh.other"]["rawFuelCode"] == "FOS"


def test_eia_capability_safely_sums_unique_leaf_cells_without_creating_zero() -> None:
    payload = {
        "response": {
            "frequency": "annual",
            "data": [
                {"period": "2024", "stateId": "TX", "producerTypeId": "IPP",
                 "fuelTypeId": "NG", "capability": "100", "capability-units": "megawatts"},
                {"period": "2024", "stateId": "TX", "producerTypeId": "IPP",
                 "fuelTypeId": "SUN", "capability": "", "capability-units": "megawatts"},
            ],
        },
    }
    record = normalize_eia_state(
        payload,
        route_id="capability",
        state_mapping={"TX": "US-TEXAS"},
        active_geography_ids={"US-TEXAS"},
    )[0]
    assert record["dependableCapacityMw"] == 100
    assert len(record["sourceSeries"]["dependableCapacityMw"]["aggregatedFacets"]) == 2


def test_synthetic_eia_series_remain_a_backward_compatible_fallback() -> None:
    payload = {
        "response": {
            "frequency": "annual",
            "data": [
                {"period": "2024", "stateid": "TX", "series": "sales",
                 "value": "1000", "unit": "MWh"},
                {"period": "2024", "stateid": "TX", "series": "generation",
                 "fueltypeid": "ALL", "value": "900", "unit": "MWh"},
                {"period": "2024", "stateid": "TX", "series": "generation",
                 "fueltypeid": "NG", "value": "600", "unit": "MWh"},
            ],
        },
    }
    record = normalize_eia_state(
        payload,
        state_mapping={"TX": "US-TEXAS"},
        active_geography_ids={"US-TEXAS"},
    )[0]
    assert record["demandGwh"] == 1
    assert record["localGenerationGwh"] == 0.9
    assert record["generationMixGwh"] == {"gas": 0.6}


@pytest.mark.parametrize(
    ("value", "unit", "dimension", "expected"),
    [
        ("1000", "MWh", "energy", 1.0),
        ("1.5", "GWh", "energy", 1.5),
        ("2", "TWh", "energy", 2000.0),
        ("350", "MW", "power", 350.0),
        ("", "GWh", "energy", None),
    ],
)
def test_strict_unit_conversion(value: str, unit: str, dimension: str, expected: float | None) -> None:
    assert normalize_metric_value(value, unit=unit, dimension=dimension) == expected


def test_strict_unit_conversion_rejects_incompatible_or_unknown_units() -> None:
    with pytest.raises(ValueError, match="energy.*MW"):
        normalize_metric_value("4", unit="MW", dimension="energy")
    with pytest.raises(ValueError, match="power.*GWh"):
        normalize_metric_value("4", unit="GWh", dimension="power")
    with pytest.raises(ValueError, match="unsupported"):
        normalize_metric_value("4", unit="kWh", dimension="energy")
    with pytest.raises(ValueError, match="incompatible"):
        normalize_metric_value("", unit="MW", dimension="energy")


def test_mapping_is_explicit_active_and_unknown_codes_are_reported() -> None:
    assert validate_region_mapping(
        {"TX": "US-TEXAS"}, active_geography_ids={"US-TEXAS"}
    ) == {"TX": "US-TEXAS"}
    with pytest.raises(ValueError, match="inactive geography IDs.*US-OLD"):
        validate_region_mapping({"TX": "US-OLD"}, active_geography_ids={"US-TEXAS"})
    with pytest.raises(ValueError, match="unmapped source region codes.*CA"):
        validate_region_mapping(
            {"TX": "US-TEXAS"},
            active_geography_ids={"US-TEXAS"},
            observed_source_codes={"TX", "CA"},
        )


def test_curated_loader_preserves_missing_values_and_public_lineage(tmp_path: Path) -> None:
    path = tmp_path / "observations.csv"
    with path.open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=[
            "source_region_code", "country_iso3", "year", "demand_value", "demand_unit",
            "generation_value", "generation_unit", "peak_value", "peak_unit",
            "net_interchange_value", "net_interchange_unit", "observed_unmet_demand_value",
            "observed_unmet_demand_unit", "generation_mix_json", "source_id", "source_record_id",
            "source_url", "licence", "updated_at", "observation_date", "value_kind", "method_id",
        ])
        writer.writeheader()
        writer.writerow({
            "source_region_code": "TX", "country_iso3": "USA", "year": "2024",
            "demand_value": "82400", "demand_unit": "GWh",
            "generation_value": "75000", "generation_unit": "GWh",
            "peak_value": "86100", "peak_unit": "MW",
            "net_interchange_value": "", "net_interchange_unit": "GWh",
            "observed_unmet_demand_value": "", "observed_unmet_demand_unit": "GWh",
            "generation_mix_json": '{"gas":{"value":20000,"unit":"GWh"}}',
            "source_id": "ercot-2024", "source_record_id": "ercot-tx-2024",
            "source_url": "https://www.ercot.com/gridinfo/generation",
            "licence": "public-domain", "updated_at": "2025-04-01",
            "observation_date": "2024-12-31", "value_kind": "reported",
            "method_id": "ercot-annual-v1",
        })

    record = load_curated_regional_observations(
        path,
        region_mapping={"TX": "US-TEXAS"},
        active_geography_ids={"US-TEXAS"},
    )[0]
    assert record["geographyId"] == "US-TEXAS"
    assert record["netInterchangeGwh"] is None
    assert record["observedUnmetDemandGwh"] is None
    assert record["generationMixGwh"] == {"gas": 20_000}
    assert record["sourceRecordId"] == "ercot-tx-2024"
    assert record["freshnessDays"] is not None
    assert record["sourceUrl"].startswith("https://")


def test_curated_loader_rejects_non_public_or_incomplete_lineage(tmp_path: Path) -> None:
    path = tmp_path / "observations.csv"
    path.write_text(
        "source_region_code,country_iso3,year,demand_value,demand_unit,source_id,source_record_id,source_url,licence,updated_at,observation_date,value_kind,method_id\n"
        "TX,USA,2024,2,TWh,x,x-1,private://report,,2025-01-01,2024-12-31,reported,x-v1\n"
    )
    with pytest.raises(ValueError, match="public source URL|licence"):
        load_curated_regional_observations(
            path,
            region_mapping={"TX": "US-TEXAS"},
            active_geography_ids={"US-TEXAS"},
        )


def test_curated_loader_rejects_a_restricted_licence(tmp_path: Path) -> None:
    path = tmp_path / "observations.csv"
    path.write_text(
        "source_region_code,country_iso3,year,demand_value,demand_unit,source_id,source_record_id,source_url,licence,updated_at,observation_date,value_kind,method_id\n"
        "TX,USA,2024,2,TWh,x,x-1,https://example.org/data,Proprietary restricted,2025-01-01,2024-12-31,reported,x-v1\n"
    )
    with pytest.raises(ValueError, match="licence is not redistributable"):
        load_curated_regional_observations(
            path,
            region_mapping={"TX": "US-TEXAS"},
            active_geography_ids={"US-TEXAS"},
        )


def test_merge_is_field_by_field_official_first_and_order_independent() -> None:
    modelled = {
        "geographyId": "US-TEXAS", "geographyLevel": "admin_1", "countryIso3": "USA",
        "year": 2024, "period": "annual", "demandGwh": 80_000,
        "localGenerationGwh": 74_000, "peakDemandMw": 85_000,
        "netInterchangeGwh": None, "observedUnmetDemandGwh": None,
        "installedCapacityMw": None, "generationMixGwh": {}, "sourceIds": ["model-v1"],
        "sourceId": "model-v1", "sourceRecordId": "model-tx-2024", "sourceType": "modelled",
        "sourceUrl": "https://example.org/model", "licence": "CC-BY-4.0",
        "updatedAt": "2026-01-01", "observationDate": "2024-12-31",
        "valueKind": "estimated", "methodId": "allocation-v1",
    }
    official = {
        **modelled, "demandGwh": 82_400, "localGenerationGwh": None,
        "netInterchangeGwh": 7_700, "sourceIds": ["official-v1"],
        "sourceId": "official-v1", "sourceRecordId": "official-tx-2024",
        "sourceType": "official_verified", "sourceUrl": "https://example.gov/data",
        "valueKind": "reported", "methodId": "official-v1",
    }
    one = merge_regional_observations([modelled, official])[0]
    two = merge_regional_observations([official, modelled])[0]
    assert one == two
    assert one["demandGwh"] == 82_400
    assert one["localGenerationGwh"] == 74_000
    assert one["netInterchangeGwh"] == 7_700
    assert one["observedUnmetDemandGwh"] is None
    assert one["fieldProvenance"]["demandGwh"]["sourceId"] == "official-v1"
    assert one["fieldProvenance"]["localGenerationGwh"]["sourceId"] == "model-v1"


def test_separate_eia_series_merge_without_erasing_other_official_fields() -> None:
    payloads = json.loads((FIXTURES / "eia-state-sample.json").read_text())
    normalized = []
    for series in ("sales", "generation"):
        normalized.extend(normalize_eia_state(
            payloads[series],
            route_id=series,
            state_mapping={"TX": "US-TEXAS"},
            active_geography_ids={"US-TEXAS"},
        ))

    merged = merge_regional_observations(normalized)[0]
    assert merged["demandGwh"] == 82_400
    assert merged["localGenerationGwh"] == 75_000
    assert merged["fieldProvenance"]["demandGwh"]["sourceSeries"]["series"] == "sales"
    assert merged["unitMetadata"]["demandGwh"]["canonicalUnit"] == "GWh"


def test_duplicate_keys_and_conflicting_official_values_are_rejected() -> None:
    base = {
        "geographyId": "US-TEXAS", "geographyLevel": "admin_1", "countryIso3": "USA",
        "year": 2024, "period": "annual", "demandGwh": 1.0, "sourceId": "official",
        "sourceIds": ["official"], "sourceRecordId": "row-1", "sourceType": "official_verified",
        "sourceUrl": "https://example.gov/data", "licence": "public-domain",
        "updatedAt": "2025-01-01", "observationDate": "2024-12-31",
        "valueKind": "reported", "methodId": "official-v1",
    }
    with pytest.raises(ValueError, match="duplicate observation key"):
        merge_regional_observations([base, dict(base)])
    conflict = {**base, "sourceId": "official-2", "sourceIds": ["official-2"],
                "sourceRecordId": "row-2", "demandGwh": 2.0}
    with pytest.raises(ValueError, match="conflicting official values"):
        merge_regional_observations([base, conflict])


def test_eia_connector_is_opt_in_and_does_not_embed_credentials() -> None:
    connector = EiaV2Connector(base_url=None, api_key=None)
    result = connector.fetch(path="electricity/retail-sales/data/", params={}, now=None)
    assert result.state == ConnectorState.NOT_CONFIGURED
    assert result.payload is None


def test_eia_connector_fetches_configured_public_v2_resource() -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        offset = int(request.url.params["offset"])
        rows = [
            {"period": "2024", "stateid": code, "sectorid": "ALL", "sales": "1",
             "sales-units": "million kilowatt hours"}
            for code in (["TX", "CA"] if offset == 0 else ["NY"])
        ]
        return httpx.Response(200, json={
            "apiVersion": "2.1.0",
            "request": {"command": "/v2/electricity/retail-sales/data/"},
            "response": {
                "frequency": "annual", "dateFormat": "YYYY", "total": "3", "data": rows,
            },
        })

    connector = EiaV2Connector(base_url="https://api.eia.gov/v2/", api_key="test-key")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = connector.fetch(
            route_id="sales",
            params={"frequency": "annual"},
            page_size=2,
            now=datetime(2026, 6, 28, tzinfo=UTC),
            client=client,
        )

    assert result.state == ConnectorState.CURRENT
    assert result.payload is not None
    assert requested[0].url.params["frequency"] == "annual"
    assert requested[0].url.params["api_key"] == "test-key"
    assert [request.url.params["offset"] for request in requested] == ["0", "2"]
    body = json.loads(result.payload.body)
    assert len(body["response"]["data"]) == 3
    assert body["response"]["data"][0]["_routeId"] == "sales"
    assert body["apiVersion"] == "2.1.0"
    assert body["response"]["frequency"] == "annual"
    assert body["request"]["command"] == "/v2/electricity/retail-sales/data/"
    assert b"test-key" not in result.payload.body
