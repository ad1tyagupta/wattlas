from datetime import UTC, datetime
import json
from pathlib import Path

import pytest
import httpx

from grid_scope.connectors.entsoe import EntsoeConnector
from grid_scope.connectors.eurostat import parse_population
from grid_scope.connectors.gisco import filter_nuts2
from grid_scope.connectors.ember import normalize_ember_rows
from grid_scope.connectors.global_assets import load_asset_registry
from grid_scope.connectors.un_geodata import UN_BOUNDARY_DISCLAIMER, normalize_countries
from grid_scope.connectors.un_salb import normalize_salb
from grid_scope.connectors.world_bank import WorldBankConnector, parse_indicator_page
from grid_scope.models import ConnectorState
from grid_scope.storage import RawCaptureStore


def test_entsoe_without_token_is_not_configured() -> None:
    result = EntsoeConnector(token=None).fetch(now=datetime.now(UTC))
    assert result.state == ConnectorState.NOT_CONFIGURED
    assert result.payload is None


def test_identical_payloads_reuse_capture(tmp_path) -> None:
    store = RawCaptureStore(tmp_path / "raw", tmp_path / "warehouse.duckdb")

    first = store.save("gisco", b'{"type":"FeatureCollection"}', "application/json")
    second = store.save("gisco", b'{"type":"FeatureCollection"}', "application/json")

    assert first.checksum == second.checksum
    assert first.path == second.path
    assert first.path.exists()


def test_gisco_filter_keeps_only_level_two() -> None:
    collection = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"LEVL_CODE": 1, "NUTS_ID": "DE7"}},
            {"type": "Feature", "properties": {"LEVL_CODE": 2, "NUTS_ID": "DE71"}},
        ],
    }

    filtered = filter_nuts2(collection)
    assert [feature["properties"]["NUTS_ID"] for feature in filtered["features"]] == ["DE71"]


def test_eurostat_special_values_remain_missing() -> None:
    payload = {
        "id": ["geo"],
        "size": [2],
        "dimension": {
            "geo": {"category": {"index": {"DE71": 0, "NL32": 1}}},
        },
        "value": {"0": 4_100_000},
        "status": {"1": ":"},
    }

    assert parse_population(payload) == {"DE71": 4_100_000, "NL32": None}


FIXTURES = Path(__file__).parent / "fixtures"


def test_un_geodata_normalizes_country_identifiers_and_disclaimer() -> None:
    payload = json.loads((FIXTURES / "un-geodata-sample.geojson").read_text())

    result = normalize_countries(payload)

    assert len(result["features"]) == 1
    properties = result["features"][0]["properties"]
    assert properties["id"] == "AE"
    assert properties["iso3"] == "ARE"
    assert properties["m49"] == "784"
    assert properties["level"] == "country"
    assert result["metadata"]["disclaimer"] == UN_BOUNDARY_DISCLAIMER


def test_un_geodata_rejects_country_geometry_without_identifier() -> None:
    with pytest.raises(ValueError, match="identifiable country"):
        normalize_countries({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {"nam_en": "Unknown"},
            }],
        })


def test_un_salb_retains_admin_parent_relationships() -> None:
    payload = json.loads((FIXTURES / "un-salb-sample.geojson").read_text())

    result = normalize_salb(payload)
    properties = [feature["properties"] for feature in result["features"]]

    assert properties[0]["level"] == "admin_1"
    assert properties[1]["level"] == "admin_2"
    assert properties[1]["parentId"] == "AE01"
    assert {item["country"] for item in properties} == {"AE"}


def test_world_bank_preserves_nulls_and_paginates() -> None:
    pages_requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pages_requested.append(str(request.url.params["page"]))
        page = int(request.url.params["page"])
        return httpx.Response(200, json=[
            {"page": page, "pages": 2},
            [{"countryiso3code": "ARE", "value": 141.2 if page == 1 else None}],
        ])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = WorldBankConnector("EG.USE.ELEC.KH.PC", base_url="https://example.test").fetch(
            client, now=datetime.now(UTC)
        )

    assert pages_requested == ["1", "2"]
    assert result.payload is not None


def test_world_bank_page_parser_keeps_missing_value() -> None:
    _, rows = parse_indicator_page([
        {"page": 1, "pages": 1},
        [{"countryiso3code": "ARE", "value": None}],
    ])

    assert rows == [{"countryIso3": "ARE", "value": None}]


def test_ember_matches_country_codes_and_keeps_missing_values() -> None:
    rows = normalize_ember_rows([
        {"Country code": "ARE", "Country": "United Arab Emirates", "Value": "87.4"},
        {"Country code": "", "Country": "Example", "Value": ""},
    ], country_lookup={"Example": "EXM"})

    assert rows == [
        {"countryIso3": "ARE", "value": 87.4},
        {"countryIso3": "EXM", "value": None},
    ]


def test_global_assets_require_public_sources_and_normalize_types(tmp_path) -> None:
    sources_path = tmp_path / "sources.json"
    assets_path = tmp_path / "assets.json"
    sources_path.write_text(json.dumps({"sources": [{
        "id": "official-1", "name": "Official source", "tier": "A",
        "url": "https://example.com/project", "publishedAt": "2026-01-01T00:00:00Z",
    }]}))
    assets_path.write_text(json.dumps({"assets": [{
        "id": "ae-desal-1", "name": "Example plant", "geographyId": "AE",
        "category": "water_infrastructure", "subtype": "desalination",
        "lifecycle": "under_construction", "targetYear": 2027,
        "coordinates": [55.0, 25.0], "locationPrecision": "exact",
        "valueKind": "reported", "sourceIds": ["official-1"],
        "demandMw": {"low": 40, "central": 50, "high": 60},
    }]}))

    registry = load_asset_registry(assets_path, sources_path)

    assert registry["assets"][0]["category"] == "water_infrastructure"
    assert registry["assets"][0]["demandMw"]["central"] == 50
    assert registry["assets"][0]["country"] == "AE"


def test_global_assets_reject_unknown_or_non_public_source(tmp_path) -> None:
    sources_path = tmp_path / "sources.json"
    assets_path = tmp_path / "assets.json"
    sources_path.write_text(json.dumps({"sources": []}))
    assets_path.write_text(json.dumps({"assets": [{
        "id": "uncited", "name": "Uncited", "geographyId": "US",
        "category": "data_centre", "subtype": "hyperscale", "lifecycle": "announced",
        "coordinates": [-90, 30], "locationPrecision": "region_centroid",
        "valueKind": "estimated", "sourceIds": ["missing"],
        "demandMw": {"low": 90, "central": 100, "high": 120},
    }]}))

    with pytest.raises(ValueError, match="unknown source"):
        load_asset_registry(assets_path, sources_path)
