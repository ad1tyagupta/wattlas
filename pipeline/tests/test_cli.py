import pytest
from pathlib import Path

from grid_scope.cli import main, merge_asset_feeds


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


def test_daily_workflow_allows_long_public_query() -> None:
    workflow = (Path(__file__).parents[2] / ".github" / "workflows" / "refresh-data.yml").read_text()
    assert "timeout-minutes: 30" in workflow
    assert "QLEVER_OSM_URL" in workflow
