import json

from grid_scope.snapshot_builder import build_snapshot_artifacts


def test_builder_keeps_uncovered_regions_unranked() -> None:
    geometry = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {
                    "NUTS_ID": "DE71",
                    "NAME_LATN": "Darmstadt",
                    "CNTR_CODE": "DE",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {
                    "NUTS_ID": "DE72",
                    "NAME_LATN": "Gießen",
                    "CNTR_CODE": "DE",
                },
            },
        ],
    }
    curated = {
        "modelNote": "Estimated indices.",
        "sources": [{"id": "source-1", "name": "Source", "tier": "A", "url": "https://example.com", "publishedAt": "2026-01-01T00:00:00Z"}],
        "clusters": [{
            "id": "frankfurt",
            "name": "Frankfurt",
            "regionId": "DE71",
            "country": "DE",
            "coordinates": [8.6, 50.1],
            "sourceIds": ["source-1"],
            "confidence": 70,
            "drivers2030": {
                "compute_load_pressure": 88,
                "connection_scarcity": 84,
                "reinforcement_gap": 80,
                "firm_flexible_supply_gap": 60,
                "cooling_water_stress": 70,
            },
        }],
    }

    artifacts = build_snapshot_artifacts(geometry, {}, curated, "2026-06-27T04:12:00Z")
    regions = json.loads(artifacts["regions.geojson"])
    by_id = {feature["id"]: feature for feature in regions["features"]}

    assert by_id["DE71"]["properties"]["scoresByYear"]["2030"]["infrastructureDemand"] == 78
    assert by_id["DE72"]["properties"]["scoresByYear"]["2030"]["infrastructureDemand"] is None
    assert by_id["DE72"]["properties"]["valueKind"] == "unavailable"
    assert len(json.loads(artifacts["projects.geojson"])["features"]) == 1
