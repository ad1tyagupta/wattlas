import json

from grid_scope.snapshot_builder import build_global_snapshot_artifacts, build_snapshot_artifacts


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
                "projected_load": 80,
                "delivery_timing": 60,
                "local_load_shock": 40,
            },
        }],
    }

    artifacts = build_snapshot_artifacts(geometry, {}, curated, "2026-06-27T04:12:00Z")
    regions = json.loads(artifacts["regions.geojson"])
    by_id = {feature["id"]: feature for feature in regions["features"]}

    assert by_id["DE71"]["properties"]["scoresByYear"]["2030"]["infrastructureDemand"] == 67
    assert by_id["DE72"]["properties"]["scoresByYear"]["2030"]["infrastructureDemand"] is None
    assert by_id["DE72"]["properties"]["valueKind"] == "unavailable"
    assert len(json.loads(artifacts["projects.geojson"])["features"]) == 1


def test_global_builder_publishes_countries_assets_and_category_scores() -> None:
    countries = {
        "type": "FeatureCollection",
        "metadata": {"disclaimer": "UN boundary disclaimer"},
        "features": [
            {
                "type": "Feature",
                "id": "AE",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {"id": "AE", "name": "United Arab Emirates", "country": "AE", "level": "country"},
            },
            {
                "type": "Feature",
                "id": "US",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {"id": "US", "name": "United States", "country": "US", "level": "country"},
            },
        ],
    }
    registry = {
        "sources": [{"id": "official-1", "name": "Official", "tier": "A", "url": "https://example.com", "publishedAt": "2026-01-01T00:00:00Z"}],
        "assets": [{
            "id": "ae-desal-1", "name": "Example desalination plant", "operator": "Example",
            "geographyId": "AE", "country": "AE", "category": "water_infrastructure",
            "subtype": "desalination", "lifecycle": "under_construction", "targetYear": 2027,
            "coordinates": [55, 25], "locationPrecision": "exact", "valueKind": "estimated",
            "sourceIds": ["official-1"], "demandMw": {"low": 40, "central": 50, "high": 60},
        }],
    }

    artifacts = build_global_snapshot_artifacts(
        countries=countries,
        regions={"type": "FeatureCollection", "features": []},
        registry=registry,
        generated_at="2026-06-27T04:12:00Z",
    )

    assert set(artifacts) == {"countries.geojson", "regions.geojson", "assets.geojson", "evidence.json"}
    country_data = json.loads(artifacts["countries.geojson"])
    by_id = {feature["id"]: feature for feature in country_data["features"]}
    assert by_id["AE"]["properties"]["scores"]["infrastructureDemand"] is not None
    assert by_id["AE"]["properties"]["categoryScoresByYear"]["2030"]["water_infrastructure"]["infrastructureDemand"] is not None
    assert by_id["US"]["properties"]["valueKind"] == "unavailable"
    assert country_data["metadata"]["disclaimer"] == "UN boundary disclaimer"
    asset_data = json.loads(artifacts["assets.geojson"])
    assert asset_data["features"][0]["properties"]["category"] == "water_infrastructure"


def test_operational_assets_are_context_only_and_country_counts_explain_coverage() -> None:
    countries = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "id": "US",
            "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {"id": "US", "name": "United States", "country": "US", "level": "country"},
        }],
    }
    registry = {
        "sources": [{"id": "openstreetmap-infrastructure", "name": "OpenStreetMap", "tier": "C", "url": "https://www.openstreetmap.org", "publishedAt": None}],
        "assets": [{
            "id": "osm-node-101", "name": "Mapped data centre", "operator": "Example",
            "geographyId": "US", "country": "US", "category": "data_centre",
            "subtype": "other_data_centre", "lifecycle": "operational", "targetYear": None,
            "coordinates": [-77.1, 38.9], "locationPrecision": "exact", "valueKind": "observed",
            "sourceIds": ["openstreetmap-infrastructure"], "demandMw": None,
            "sourceType": "community_mapped", "sourceUrl": "https://www.openstreetmap.org/node/101",
        }],
    }

    artifacts = build_global_snapshot_artifacts(
        countries=countries,
        regions={"type": "FeatureCollection", "features": []},
        registry=registry,
        generated_at="2026-06-27T12:00:00Z",
    )
    properties = json.loads(artifacts["countries.geojson"])["features"][0]["properties"]

    assert properties["scores"]["infrastructureDemand"] is None
    assert properties["demandMwByYear"]["2030"]["combined"] is None
    assert properties["assetSummary"] == {
        "total": 1,
        "operational": 1,
        "planned": 0,
        "dataCentres": 1,
        "waterInfrastructure": 0,
        "officialVerified": 0,
        "communityMapped": 1,
    }
    asset = json.loads(artifacts["assets.geojson"])["features"][0]
    assert asset["properties"]["sourceType"] == "community_mapped"
    assert asset["properties"]["sourceUrl"].endswith("/node/101")
