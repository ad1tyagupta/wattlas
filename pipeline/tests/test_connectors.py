from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest
import httpx
import duckdb

from grid_scope.connectors.entsoe import EntsoeConnector
from grid_scope.connectors.eurostat import parse_population
from grid_scope.connectors.gisco import filter_nuts2
from grid_scope.connectors.ember import normalize_ember_rows
from grid_scope.connectors.global_assets import load_asset_registry
from grid_scope.connectors.geoboundaries import normalize_adm1, validate_india_adm1
from grid_scope.connectors.gem_power import GemPowerConnector, parse_gem_power
from grid_scope.connectors.osm_infrastructure import OsmInfrastructureConnector, parse_qlever_assets
from grid_scope.connectors.osm_power import QLEVER_POWER_QUERY, OsmPowerConnector, parse_qlever_power
from grid_scope.connectors.un_geodata import UN_BOUNDARY_DISCLAIMER, normalize_countries
from grid_scope.connectors.un_salb import normalize_salb
from grid_scope.connectors.wri_power import WriPowerConnector, parse_wri_power
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


def test_identical_capture_advances_success_time_without_rewriting_body(tmp_path) -> None:
    store = RawCaptureStore(tmp_path / "raw", tmp_path / "warehouse.duckdb")
    body = b'{"same":true}'
    first = store.save("gisco", body, "application/json")
    original_mtime = first.path.stat().st_mtime_ns
    with duckdb.connect(str(store.database_path)) as connection:
        connection.execute(
            "UPDATE raw_captures SET retrieved_at = ? WHERE source_id = ?",
            [datetime(2000, 1, 1, tzinfo=UTC), "gisco"],
        )
    store.save("gisco", body, "application/json")
    latest = store.latest_capture("gisco")
    assert latest is not None
    assert latest.retrieved_at.year > 2000
    assert first.path.stat().st_mtime_ns == original_mtime


def test_latest_capture_skips_tampered_newest_and_uses_older_valid_file(tmp_path) -> None:
    store = RawCaptureStore(tmp_path / "raw", tmp_path / "warehouse.duckdb")
    valid = store.save("gem_power", b'{"records":[{"id":"valid"}]}', "application/json")
    tampered = store.save(
        "gem_power", b'{"records":[{"id":"newer"}]}', "application/json"
    )
    tampered.path.write_bytes(b"tampered")
    bad_body = b'{"records":[{"id":"bad"}]}'
    bad_checksum = sha256(bad_body).hexdigest()
    bad_path = tmp_path / "outside.json"
    bad_path.write_bytes(bad_body)
    with duckdb.connect(str(store.database_path)) as connection:
        connection.execute(
            "INSERT INTO raw_captures VALUES (?, ?, ?, ?, ?)",
            ["gem_power", bad_checksum, str(bad_path), "application/json",
                 datetime(2099, 1, 1, tzinfo=UTC)],
        )
        connection.execute(
            "UPDATE raw_captures SET retrieved_at = ? WHERE source_id = ? AND checksum = ?",
            [datetime(2098, 1, 1, tzinfo=UTC), "gem_power", tampered.checksum],
        )
    assert store.latest_path("gem_power") == valid.path


def test_latest_capture_rejects_tamper_symlink_and_source_path_escape(tmp_path) -> None:
    store = RawCaptureStore(tmp_path / "raw", tmp_path / "warehouse.duckdb")
    capture = store.save("wri_power", b'{"records":[1]}', "application/json")
    capture.path.write_bytes(b"tampered")
    assert store.latest_capture("wri_power") is None

    target = tmp_path / "target.json"
    body = b'{"records":[2]}'
    target.write_bytes(body)
    checksum = sha256(body).hexdigest()
    link = store.raw_dir / "osm_power" / f"{checksum}.json"
    link.parent.mkdir()
    os.symlink(target, link)
    with duckdb.connect(str(store.database_path)) as connection:
        connection.execute(
            "INSERT INTO raw_captures VALUES (?, ?, ?, ?, ?)",
            ["osm_power", checksum, str(link), "application/json", datetime.now(UTC)],
        )
    assert store.latest_capture("osm_power") is None

    media = store.save("media_source", b'{"records":[3]}', "application/json")
    with duckdb.connect(str(store.database_path)) as connection:
        connection.execute(
            "UPDATE raw_captures SET media_type = ? WHERE source_id = ? AND checksum = ?",
            ["application/octet-stream", "media_source", media.checksum],
        )
    assert store.latest_capture("media_source") is None
    with pytest.raises(ValueError, match="source ID"):
        store.save("../escape", b"bad", "application/json")


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
    assert "website" not in parse_qlever_assets(payload, observed_at="2026-06-27T12:00:00Z")[1]


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


def test_gem_power_parser_preserves_unit_hierarchy_capacity_and_provenance() -> None:
    records = parse_gem_power(FIXTURES / "gem-power-sample.csv")

    nuclear = next(item for item in records if item["externalIds"]["gemUnit"] == "GEM-U-1")

    assert nuclear["category"] == "power_generation"
    assert nuclear["technology"] == "nuclear"
    assert nuclear["capacityMw"] == {"low": 1_200, "central": 1_200, "high": 1_200}
    assert nuclear["capacityValueKind"] == "reported"
    assert nuclear["plantId"] == "gem-plant-GEM-P-1"
    assert nuclear["unitId"] == "gem-unit-GEM-U-1"
    assert nuclear["lifecycle"] == "operational"
    assert nuclear["coordinates"] == [77.25, 28.62]
    assert nuclear["owner"] == "Public Energy Authority"
    assert nuclear["operator"] == "National Nuclear Operator"
    assert nuclear["sourceUrl"] == "https://www.gem.wiki/Example_Nuclear"
    assert nuclear["licence"] == "CC-BY-4.0"
    assert nuclear["updatedAt"] == "2026-03-15"


def test_gem_power_parser_normalizes_lifecycles_and_keeps_missing_capacity_unavailable() -> None:
    records = parse_gem_power(FIXTURES / "gem-power-sample.csv")

    by_unit = {item["externalIds"]["gemUnit"]: item for item in records}
    assert by_unit["GEM-U-2"]["lifecycle"] == "under_construction"
    assert by_unit["GEM-U-2"]["technology"] == "solar"
    assert by_unit["GEM-U-3"]["lifecycle"] == "announced"
    assert by_unit["GEM-U-3"]["technology"] == "wind"
    assert by_unit["GEM-U-3"]["capacityMw"] is None
    assert by_unit["GEM-U-3"]["capacityValueKind"] == "unavailable"
    assert by_unit["GEM-U-4"]["lifecycle"] == "retired"
    assert by_unit["GEM-U-5"]["lifecycle"] == "cancelled"
    assert by_unit["GEM-U-5"]["technology"] == "gas"
    assert by_unit["GEM-U-6"]["lifecycle"] == "shelved"
    assert by_unit["GEM-U-7"]["lifecycle"] == "paused"
    assert by_unit["GEM-U-7"]["rawStatus"] == "Mothballed"
    assert by_unit["GEM-U-8"]["lifecycle"] == "announced"
    assert by_unit["GEM-U-9"]["lifecycle"] == "cancelled"
    assert by_unit["GEM-U-10"]["lifecycle"] == "paused"


def test_gem_power_parser_accepts_real_gipt_hierarchy_headers() -> None:
    records = parse_gem_power(FIXTURES / "gem-power-real-headers-sample.csv")

    assert records[0]["plantId"] == "gem-plant-GEM-LOC-900"
    assert records[0]["unitId"] == "gem-unit-GEM-PHASE-901"
    assert records[0]["plantName"] == "Real Header Wind Project"
    assert records[0]["name"] == "Real Header Wind Phase 1"
    assert records[0]["technology"] == "wind"
    assert records[0]["country"] == "Denmark"


def test_gem_power_parser_resolves_workbook_relationships_and_finds_header_row(tmp_path) -> None:
    workbook = tmp_path / "realistic-gipt.xlsx"

    def row_xml(row_number: int, cells: list[str]) -> str:
        return "<row r=\"{}\">{}</row>".format(
            row_number,
            "".join(
                f'<c r="{chr(65 + index)}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>'
                for index, value in enumerate(cells)
            ),
        )

    about_sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{row_xml(1, ['Global Integrated Power Tracker'])}</sheetData></worksheet>"
    )
    headers = [
        "GEM Location ID", "GEM Unit/Phase ID", "Project/Plant Name", "Unit/Phase Name",
        "Country/Area", "Latitude", "Longitude", "Status", "Capacity (MW)", "Technology",
    ]
    values = [
        "GEM-REAL-1", "GEM-REAL-U-1", "Relationship Solar", "Relationship Solar Phase",
        "Spain", "40.4", "-3.7", "Operating", "88", "Photovoltaic",
    ]
    units_sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        f"{row_xml(1, ['GIPT units export'])}{row_xml(3, headers)}{row_xml(4, values)}"
        "</sheetData></worksheet>"
    )
    workbook_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
      <sheets>
        <sheet name="About" sheetId="1" r:id="rIdAbout"/>
        <sheet name="Units and phases" sheetId="2" r:id="rIdUnits"/>
      </sheets>
    </workbook>"""
    relationships = """<?xml version="1.0" encoding="UTF-8"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdAbout" Type="worksheet" Target="worksheets/sheet7.xml"/>
      <Relationship Id="rIdUnits" Type="worksheet" Target="worksheets/sheet2.xml"/>
    </Relationships>"""
    with ZipFile(workbook, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet7.xml", about_sheet)
        archive.writestr("xl/worksheets/sheet2.xml", units_sheet)

    records = parse_gem_power(workbook)

    assert records[0]["externalIds"] == {
        "gemPlant": "GEM-REAL-1", "gemUnit": "GEM-REAL-U-1",
    }
    assert records[0]["name"] == "Relationship Solar Phase"


def test_wri_power_parser_preserves_fuels_generation_history_and_source_details() -> None:
    payload = json.loads((FIXTURES / "wri-power-sample.json").read_text())

    records = parse_wri_power(payload, updated_at="2021-06-01")

    gas = next(item for item in records if item["externalIds"]["wri"] == "WRI-100")
    assert gas["technology"] == "gas"
    assert gas["primaryFuel"] == "CCGT"
    assert gas["secondaryFuel"] == "Oil"
    assert gas["capacityMw"]["central"] == 640
    assert gas["generationHistoryGwh"] == {"2017": 2_812.5, "2018": 2_900.0}
    assert gas["coordinates"] == [-77.04, 38.91]
    assert gas["owner"] == "Grid Power LLC"
    assert gas["operator"] == "Grid Operations Inc"
    assert gas["sourceUrl"] == "https://example.org/wri/WRI-100"
    assert gas["licence"] == "CC-BY-4.0"
    assert gas["updatedAt"] == "2021-06-01"


def test_wri_power_parser_uses_latest_generation_year_independent_of_json_order() -> None:
    payload = {"data": [{
        "gppd_idnr": "WRI-ORDER", "name": "Ordering Plant", "latitude": "", "longitude": "",
        "capacity_mw": 100, "primary_fuel": "Gas", "generation_gwh_2018": 800,
        "generation_gwh_2017": 700,
    }]}

    record = parse_wri_power(payload)[0]

    assert record["coordinates"] is None
    assert record["generationHistoryGwh"] == {"2017": 700, "2018": 800}
    assert record["reportedGenerationGwh"]["central"] == 800


def test_wri_power_parser_uses_and_preserves_geojson_point_geometry() -> None:
    payload = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [12.5, 41.9]},
        "properties": {
            "gppd_idnr": "WRI-GEO-1", "name": "GeoJSON Plant",
            "capacity_mw": 50, "primary_fuel": "Solar",
        },
    }]}

    record = parse_wri_power(payload)[0]

    assert record["coordinates"] == [12.5, 41.9]
    assert record["sourceGeometry"] == {"type": "Point", "coordinates": [12.5, 41.9]}


def test_wri_power_parser_rejects_non_point_geojson_fallback() -> None:
    payload = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": []},
        "properties": {
            "gppd_idnr": "WRI-GEO-BAD", "name": "Bad Geometry",
            "capacity_mw": 50, "primary_fuel": "Solar",
        },
    }]}

    with pytest.raises(ValueError, match="GeoJSON Point"):
        parse_wri_power(payload)


def test_wri_power_parser_accepts_valid_three_dimensional_geojson_point() -> None:
    payload = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [7.4, 46.9, 540]},
        "properties": {
            "gppd_idnr": "WRI-GEO-3D", "name": "Alpine Hydro",
            "capacity_mw": 25, "primary_fuel": "Hydro",
        },
    }]}

    record = parse_wri_power(payload)[0]

    assert record["coordinates"] == [7.4, 46.9]
    assert record["sourceGeometry"]["coordinates"] == [7.4, 46.9, 540]


def test_osm_power_parser_keeps_only_utility_scale_plants_and_normalizes_aliases() -> None:
    payload = json.loads((FIXTURES / "qlever-osm-power-sample.json").read_text())

    records = parse_qlever_power(payload, observed_at="2026-06-28T10:00:00Z")

    assert [item["externalIds"]["osm"] for item in records] == ["way/701", "relation/702"]
    assert [item["technology"] for item in records] == ["solar", "wind"]
    assert records[0]["capacityMw"]["central"] == 75
    assert records[1]["capacityMw"] is None
    assert records[0]["sourceType"] == "community_mapped"
    assert records[0]["sourceUrl"] == "https://www.openstreetmap.org/way/701"
    assert records[0]["licence"] == "ODbL-1.0"
    assert records[0]["owner"] == "Sun Holdings"
    assert records[0]["operator"] == "Sun Operations"
    assert records[0]["utilityScaleBasis"] == "reported_capacity_at_least_1mw"
    assert records[1]["utilityScaleBasis"] == "planned_or_construction_lifecycle"


def test_osm_power_query_excludes_explicit_household_and_rooftop_records_server_side() -> None:
    assert 'LCASE(STR(?location)) NOT IN ("roof", "rooftop")' in QLEVER_POWER_QUERY
    assert (
        'LCASE(STR(?scale)) NOT IN ("household", "residential", "domestic")'
        in QLEVER_POWER_QUERY
    )


def test_osm_power_query_uses_real_lifecycle_tag_branches() -> None:
    assert "UNION" in QLEVER_POWER_QUERY
    assert 'osmkey:power "plant"' in QLEVER_POWER_QUERY
    assert "Key:construction:power" in QLEVER_POWER_QUERY
    assert 'osmkey:power "construction"' in QLEVER_POWER_QUERY
    assert "Key:proposed:power" in QLEVER_POWER_QUERY
    assert 'osmkey:power "proposed"' in QLEVER_POWER_QUERY
    assert 'BIND("under_construction" AS ?lifecycle)' in QLEVER_POWER_QUERY
    assert 'BIND("announced" AS ?lifecycle)' in QLEVER_POWER_QUERY


def test_osm_power_parser_preserves_lifecycle_evidence_and_dedupes_deterministically() -> None:
    operational = {
        "element": {"value": "https://www.openstreetmap.org/way/950"},
        "name": {"value": "Transition Plant"},
        "geometry": {"value": "POINT(10 20)"},
        "source": {"value": "gas"},
        "lifecycle": {"value": "operational"},
        "rawLifecycle": {"value": "power=plant"},
    }
    construction = {
        **operational,
        "lifecycle": {"value": "under_construction"},
        "rawLifecycle": {"value": "construction:power=plant"},
    }

    first = parse_qlever_power(
        {"results": {"bindings": [operational, construction]}},
        observed_at="2026-06-28T10:00:00Z",
    )
    second = parse_qlever_power(
        {"results": {"bindings": [construction, operational]}},
        observed_at="2026-06-28T10:00:00Z",
    )

    assert first == second
    assert first[0]["lifecycle"] == "under_construction"
    assert first[0]["rawStatus"] == "construction:power=plant"


def test_osm_power_parser_reads_thousands_separated_megawatts() -> None:
    payload = {"results": {"bindings": [{
        "element": {"value": "https://www.openstreetmap.org/way/900"},
        "name": {"value": "Large Hydro"},
        "geometry": {"value": "POINT(10 20)"},
        "source": {"value": "hydro"},
        "output": {"value": "1,200 MW"},
    }]}}

    record = parse_qlever_power(payload, observed_at="2026-06-28T10:00:00Z")[0]

    assert record["capacityMw"]["central"] == 1_200


def test_osm_power_parser_reads_dot_decimal_megawatts() -> None:
    payload = {"results": {"bindings": [{
        "element": {"value": "https://www.openstreetmap.org/way/901"},
        "name": {"value": "Decimal Plant"},
        "geometry": {"value": "POINT(10 20)"},
        "source": {"value": "gas"},
        "output": {"value": "1.2 MW"},
    }]}}

    record = parse_qlever_power(payload, observed_at="2026-06-28T10:00:00Z")[0]

    assert record["capacityMw"]["central"] == 1.2


@pytest.mark.parametrize("reported_output", ["1,20 MW", "50 MW; 30 MW"])
def test_osm_power_parser_rejects_ambiguous_capacity_formats(reported_output) -> None:
    payload = {"results": {"bindings": [{
        "element": {"value": "https://www.openstreetmap.org/way/902"},
        "name": {"value": "Ambiguous Capacity Plant"},
        "geometry": {"value": "POINT(10 20)"},
        "source": {"value": "gas"},
        "output": {"value": reported_output},
    }]}}

    with pytest.raises(ValueError, match="ambiguous|malformed"):
        parse_qlever_power(payload, observed_at="2026-06-28T10:00:00Z")


def test_osm_power_parser_rejects_conflicting_capacity_bindings() -> None:
    binding = {
        "element": {"value": "https://www.openstreetmap.org/way/903"},
        "name": {"value": "Conflicting Capacity Plant"},
        "geometry": {"value": "POINT(10 20)"},
        "source": {"value": "gas"},
        "lifecycle": {"value": "operational"},
    }
    payload = {"results": {"bindings": [
        {**binding, "output": {"value": "50 MW"}},
        {**binding, "output": {"value": "30 MW"}},
    ]}}

    with pytest.raises(ValueError, match="conflicting OSM capacity"):
        parse_qlever_power(payload, observed_at="2026-06-28T10:00:00Z")


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (parse_wri_power, {"data": [{
            "gppd_idnr": "BAD", "name": "Bad", "latitude": 95, "longitude": 0,
            "capacity_mw": 10, "primary_fuel": "Solar",
        }]}),
        (parse_wri_power, {"data": [{
            "gppd_idnr": "BAD", "name": "Bad", "latitude": 1, "longitude": 1,
            "capacity_mw": -10, "primary_fuel": "Solar",
        }]}),
    ],
)
def test_power_parsers_reject_malformed_coordinates_and_impossible_capacity(parser, payload) -> None:
    with pytest.raises(ValueError, match="coordinates|capacity"):
        parser(payload)


def test_gem_power_connector_is_not_configured_without_public_release() -> None:
    result = GemPowerConnector(path=None, url=None).fetch(now=datetime(2026, 6, 28, tzinfo=UTC))

    assert result.state == ConnectorState.NOT_CONFIGURED
    assert result.payload is None


def test_gem_power_parser_reads_xlsx_without_a_dataframe_dependency(tmp_path) -> None:
    workbook = tmp_path / "gem-power.xlsx"
    headers = [
        "Plant ID", "Unit ID", "Project Name", "Unit Name", "Latitude", "Longitude",
        "Status", "Capacity (MW)", "Technology", "GEM Wiki URL", "Last Updated",
    ]
    values = [
        "GEM-X-1", "GEM-X-U-1", "Workbook Solar", "Workbook Solar Unit", "10", "20",
        "Operating", "42", "Photovoltaic", "https://www.gem.wiki/Workbook_Solar", "2026-03-15",
    ]

    def row_xml(row_number: int, cells: list[str]) -> str:
        return "<row r=\"{}\">{}</row>".format(
            row_number,
            "".join(
                f'<c r="{chr(65 + index)}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>'
                for index, value in enumerate(cells)
            ),
        )

    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        f"{row_xml(1, headers)}{row_xml(2, values)}"
        "</sheetData></worksheet>"
    )
    with ZipFile(workbook, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)

    records = parse_gem_power(workbook)

    assert records[0]["externalIds"] == {"gemPlant": "GEM-X-1", "gemUnit": "GEM-X-U-1"}
    assert records[0]["technology"] == "solar"
    assert records[0]["capacityMw"]["central"] == 42


def test_power_connectors_enforce_production_coverage_guards() -> None:
    gem = GemPowerConnector(path=FIXTURES / "gem-power-sample.csv", minimum_records=100)
    with pytest.raises(ValueError, match="too few GEM power records"):
        gem.fetch(now=datetime(2026, 6, 28, tzinfo=UTC))

    wri_payload = (FIXTURES / "wri-power-sample.json").read_bytes()
    osm_payload = json.loads((FIXTURES / "qlever-osm-power-sample.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=wri_payload, headers={"content-type": "application/json"})
        return httpx.Response(200, json=osm_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="too few WRI power records"):
            WriPowerConnector("https://example.test/wri.json", minimum_records=100).fetch(
                client, now=datetime(2026, 6, 28, tzinfo=UTC)
            )
        with pytest.raises(ValueError, match="too few OSM power records"):
            OsmPowerConnector("https://example.test/sparql", minimum_records=100).fetch(
                client, now=datetime(2026, 6, 28, tzinfo=UTC)
            )


def test_power_connectors_capture_release_checksum_and_attribution() -> None:
    wri_payload = (FIXTURES / "wri-power-sample.json").read_bytes()
    osm_payload = json.loads((FIXTURES / "qlever-osm-power-sample.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=wri_payload, headers={"content-type": "application/json"})
        assert request.headers["content-type"] == "application/sparql-query"
        return httpx.Response(200, json=osm_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        wri_result = WriPowerConnector("https://example.test/wri.json", minimum_records=1).fetch(
            client, now=datetime(2026, 6, 28, tzinfo=UTC)
        )
        osm_result = OsmPowerConnector("https://example.test/sparql", minimum_records=1).fetch(
            client, now=datetime(2026, 6, 28, tzinfo=UTC)
        )

    wri_body = json.loads(wri_result.payload.body)
    osm_body = json.loads(osm_result.payload.body)
    assert len(wri_body["upstreamChecksumSha256"]) == 64
    assert wri_body["sourceUrl"] == "https://example.test/wri.json"
    assert all(record["updatedAt"] is None for record in wri_body["records"])
    assert osm_body["licence"] == "ODbL-1.0"
    assert osm_body["attribution"] == "© OpenStreetMap contributors"
    assert all(record["updatedAt"] is None for record in osm_body["records"])
