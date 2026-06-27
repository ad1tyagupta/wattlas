from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from grid_scope.connectors.entsoe import EntsoeConnector
from grid_scope.connectors.eurostat import parse_population
from grid_scope.connectors.gisco import filter_nuts2
from grid_scope.connectors.un_geodata import UN_BOUNDARY_DISCLAIMER, normalize_countries
from grid_scope.connectors.un_salb import normalize_salb
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
