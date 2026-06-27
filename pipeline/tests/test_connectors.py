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
from grid_scope.connectors.geoboundaries import normalize_adm1, validate_india_adm1
from grid_scope.connectors.osm_infrastructure import OsmInfrastructureConnector, parse_qlever_assets
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


def test_un_geodata_ignores_internal_pseudo_country_polygons() -> None:
    result = normalize_countries({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {"iso2cd": "xp", "iso3cd": "xap", "m49_cd": "356", "nam_en": ""},
        }],
    })

    assert result["features"] == []


def test_un_geodata_ignores_status_99_disputed_area_polygons() -> None:
    result = normalize_countries({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {"iso2cd": "SD", "iso3cd": "SDN", "m49_cd": "729", "nam_en": "", "stscod": 99},
        }],
    })

    assert result["features"] == []


def test_un_geodata_ignores_boundary_line_layers() -> None:
    result = normalize_countries({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            "properties": {"iso2cd": "AQ", "iso3cd": "ATA", "m49_cd": "010"},
        }],
    })

    assert result["features"] == []


def test_un_geodata_merges_repeated_country_polygons() -> None:
    source = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {"iso2cd": "US", "iso3cd": "USA", "m49_cd": "840", "nam_en": "United States of America"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 2]]]},
                "properties": {"iso2cd": "US", "iso3cd": "USA", "m49_cd": "840", "nam_en": "United States of America"},
            },
        ],
    }

    result = normalize_countries(source)

    assert len(result["features"]) == 1
    assert result["features"][0]["id"] == "US"
    assert result["features"][0]["geometry"]["type"] == "MultiPolygon"
    assert len(result["features"][0]["geometry"]["coordinates"]) == 2


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
    assert registry["assets"][0]["sourceType"] == "official_verified"
    assert registry["assets"][0]["sourceUrl"] == "https://example.com/project"


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


def test_qlever_osm_parser_normalizes_geometry_lifecycle_and_provenance() -> None:
    payload = json.loads((FIXTURES / "qlever-osm-infrastructure-sample.json").read_text())

    assets = parse_qlever_assets(payload, observed_at="2026-06-27T12:00:00Z")

    assert len(assets) == 3
    expected_core = {
        "id": "osm-node-101",
        "name": "Alpha DC",
        "operator": "Alpha Cloud",
        "geographyId": "UNASSIGNED",
        "category": "data_centre",
        "subtype": "other_data_centre",
        "lifecycle": "operational",
        "targetYear": None,
        "coordinates": [-77.1, 38.9],
        "locationPrecision": "exact",
        "valueKind": "observed",
        "sourceIds": ["openstreetmap-infrastructure"],
        "sourceType": "community_mapped",
        "sourceUrl": "https://www.openstreetmap.org/node/101",
        "lastObservedAt": "2026-06-27T12:00:00Z",
        "demandMw": None,
    }
    assert {key: assets[0][key] for key in expected_core} == expected_core
    assert assets[1]["name"] == "Mapped desalination plant · OSM 202"
    assert assets[1]["coordinates"] == [55.0, 25.0]
    assert assets[2]["lifecycle"] == "under_construction"


def test_qlever_connector_rejects_partial_production_response() -> None:
    payload = json.loads((FIXTURES / "qlever-osm-infrastructure-sample.json").read_text())

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    connector = OsmInfrastructureConnector("https://example.test/sparql", minimum_data_centres=3_500)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="too few data-centre records"):
            connector.fetch(client, now=datetime(2026, 6, 27, tzinfo=UTC))


def test_qlever_osm_parser_preserves_rich_public_facility_details() -> None:
    payload = json.loads((FIXTURES / "qlever-osm-infrastructure-sample.json").read_text())

    asset = parse_qlever_assets(payload, observed_at="2026-06-27T12:00:00Z")[0]

    assert asset["owner"] == "Alpha Infrastructure"
    assert asset["website"] == "https://alpha.example/dc"
    assert asset["facilityRef"] == "IAD-01"
    assert asset["address"] == {
        "street": "Compute Avenue", "houseNumber": "101", "city": "Ashburn",
        "state": "Virginia", "postcode": "20147", "country": "US",
    }
    assert asset["startDate"] == "2021"
    assert asset["reportedPower"] == "48 MW"
    assert asset["externalIds"] == {
        "osm": "node/101", "wikidata": "Q12345", "wikipedia": "en:Alpha Data Center",
    }


def test_qlever_connector_fetches_valid_small_fixture_when_threshold_is_overridden() -> None:
    payload = json.loads((FIXTURES / "qlever-osm-infrastructure-sample.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["content-type"] == "application/sparql-query"
        return httpx.Response(200, json=payload)

    connector = OsmInfrastructureConnector("https://example.test/sparql", minimum_data_centres=2)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = connector.fetch(client, now=datetime(2026, 6, 27, tzinfo=UTC))

    assert result.state == ConnectorState.CURRENT
    assert result.payload is not None
    assert len(json.loads(result.payload.body)["assets"]) == 3


def test_geoboundaries_normalizes_global_adm1_with_stable_parent_ids() -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[76, 28], [77, 28], [77, 29], [76, 28]]]},
            "properties": {"shapeID": "IND-ADM1-1", "shapeName": "Delhi", "shapeGroup": "IND", "shapeType": "ADM1"},
        }],
    }

    result = normalize_adm1(payload, iso2_lookup={"IND": "IN"})

    assert result["features"][0]["id"] == "IN-IND-ADM1-1"
    assert result["features"][0]["properties"] == {
        "id": "IN-IND-ADM1-1",
        "name": "Delhi",
        "country": "IN",
        "level": "admin_1",
        "parentId": "IN",
        "peerLevel": "admin_1",
        "sourceId": "geoboundaries-gbopen-adm1",
        "boundaryPerspective": "government_of_india",
    }


def test_india_adm1_gate_requires_arunachal_assam_jammu_kashmir_and_ladakh() -> None:
    features = [
        {"properties": {"name": name, "country": "IN"}}
        for name in ["Jammu and Kashmir", "Ladakh", "Assam", "Arunachal Pradesh"]
    ]

    validate_india_adm1(features)

    with pytest.raises(ValueError, match="Arunachal Pradesh"):
        validate_india_adm1(features[:-1])
