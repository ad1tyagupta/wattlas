import json

import pytest

from grid_scope.generator_artifacts import build_generator_artifacts
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

    assert set(artifacts) == {
        "countries.geojson", "admin1.geojson", "regions.geojson", "assets.geojson",
        "regional-energy.json", "generator-overview.geojson", "generators/index.json",
        "evidence.json",
    }
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


def test_global_builder_assigns_assets_to_adm1_and_overrides_india_outline() -> None:
    countries = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "id": "IN",
            "geometry": {"type": "Polygon", "coordinates": [[[60, 5], [90, 5], [90, 35], [60, 5]]]},
            "properties": {"id": "IN", "name": "India", "country": "IN", "level": "country"},
        }],
    }
    india_outline = {"type": "Polygon", "coordinates": [[[68, 7], [97, 7], [97, 37], [68, 7]]]}
    admin1 = {
        "type": "FeatureCollection",
        "metadata": {"indiaCountryGeometry": india_outline, "indiaBoundaryPerspective": "Government of India"},
        "features": [{
            "type": "Feature", "id": "IN-ASSAM",
            "geometry": {"type": "Polygon", "coordinates": [[[90, 24], [96, 24], [96, 28], [90, 28], [90, 24]]]},
            "properties": {"id": "IN-ASSAM", "name": "Assam", "country": "IN", "level": "admin_1", "parentId": "IN", "peerLevel": "admin_1"},
        }],
    }
    registry = {
        "sources": [{"id": "osm", "name": "OSM", "tier": "C", "url": "https://www.openstreetmap.org", "publishedAt": None}],
        "assets": [{
            "id": "asset-1", "name": "Assam facility", "geographyId": "IN", "country": "IN",
            "category": "data_centre", "subtype": "other_data_centre", "lifecycle": "operational",
            "coordinates": [92, 26], "locationPrecision": "exact", "valueKind": "observed",
            "sourceIds": ["osm"], "sourceType": "community_mapped", "demandMw": None,
        }],
    }

    artifacts = build_global_snapshot_artifacts(
        countries=countries, admin1=admin1,
        regions={"type": "FeatureCollection", "features": []},
        registry=registry, generated_at="2026-06-28T00:00:00Z",
    )

    assert "admin1.geojson" in artifacts
    country = json.loads(artifacts["countries.geojson"])["features"][0]
    assert country["geometry"] == india_outline
    assert country["properties"]["boundaryPerspective"] == "Government of India"
    region = json.loads(artifacts["admin1.geojson"])["features"][0]
    assert region["properties"]["assetSummary"]["total"] == 1
    asset = json.loads(artifacts["assets.geojson"])["features"][0]
    assert asset["properties"]["geographyId"] == "IN-ASSAM"


def _energy_forecast(year: int, score: float = 72) -> dict:
    return {
        "year": year,
        "metrics": {
            "demandGwh": {"low": 900, "central": 1000, "high": 1100},
            "localGenerationGwh": {"low": 700, "central": 800, "high": 900},
            "localGenerationGapGwh": {"low": 0, "central": 200, "high": 400},
            "netBalanceGwh": None,
            "observedUnmetDemandGwh": None,
            "installedCapacityMw": 400,
            "dependableCapacityMw": {"low": 200, "central": 250, "high": 300},
            "peakDemandMw": {"low": 120, "central": 130, "high": 140},
        },
        "powerBalance": {"score": score, "coverage": 75, "status": "rankable"},
        "methodId": "regional-balance-v1",
        "sourceIds": ["public-grid-source"],
        "confidence": 78,
        "coverage": 80,
        "valueKind": "estimated",
    }


def _generator(**overrides: object) -> dict:
    row = {
        "id": "plant-us-ca-solar",
        "name": "California Solar One",
        "country": "US",
        "geographyId": "US-CA",
        "coordinates": [-119.5, 36.5],
        "technologies": ["solar"],
        "operatingCapacityMw": 120.0,
        "plannedCapacityMw": 30.0,
        "unitCount": 2,
        "sourceIds": ["public-plant-registry"],
    }
    row.update(overrides)
    return row


def test_global_builder_publishes_compact_energy_and_sharded_generators() -> None:
    countries = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "id": "US",
            "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {"id": "US", "name": "United States", "country": "US"},
        }],
    }
    admin1 = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "id": "US-CA",
            "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {
                "id": "US-CA", "name": "California", "country": "US",
                "parentId": "US",
            },
        }],
    }
    forecasts = {"US-CA": [_energy_forecast(year) for year in range(2026, 2032)]}
    plants = [_generator()]

    artifacts = build_global_snapshot_artifacts(
        countries=countries,
        admin1=admin1,
        regions={"type": "FeatureCollection", "features": []},
        registry={"sources": [], "assets": []},
        generated_at="2026-06-30T00:00:00Z",
        regional_energy=forecasts,
        power_plants=plants,
        population_records=[{
            "geographyId": "US-CA", "year": 2030, "population": 39_000_000,
            "sourceYear": 2025, "valueKind": "estimated", "confidence": 82,
            "methodId": "worldpop-projection-v1", "sourceIds": ["worldpop-global2"],
        }],
    )

    compact = json.loads(artifacts["admin1.geojson"])["features"][0]["properties"]
    assert compact["population"] == 39_000_000
    assert compact["populationYear"] == 2030
    assert compact["populationSourceYear"] == 2025
    assert compact["scores"]["powerBalance"] == 72
    assert compact["powerBalanceYear"] == 2030
    assert "regionalEnergy" not in compact
    assert "generators" not in compact
    assert "methodId" not in compact
    energy = json.loads(artifacts["regional-energy.json"])
    assert list(energy) == ["US-CA"]
    assert [row["year"] for row in energy["US-CA"]] == list(range(2026, 2032))
    overview = json.loads(artifacts["generator-overview.geojson"])
    assert overview["features"][0]["properties"] == {
        "geographyId": "US-CA",
        "country": "US",
        "count": 1,
        "capacityMw": 150.0,
        "operatingCapacityMw": 120.0,
        "plannedCapacityMw": 30.0,
        "technologyMixMw": {"solar": 150.0},
        "dominantTechnology": "solar",
    }
    index = json.loads(artifacts["generators/index.json"])
    assert index["countries"]["US"]["path"] == "generators/US.geojson"
    assert index["countries"]["US"]["featureCount"] == 1
    assert len(index["countries"]["US"]["checksum"]) == 64
    shard = json.loads(artifacts["generators/US.geojson"])
    assert shard["features"][0]["properties"]["sourceIds"] == ["public-plant-registry"]
    assert index["totals"]["featureCount"] == len(shard["features"])
    assert index["totals"]["capacityMw"] == 150.0


def test_generator_artifacts_reject_unknown_assignments_and_duplicate_ids() -> None:
    countries = {
        "type": "FeatureCollection",
        "features": [{
            "id": "US", "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {"id": "US"},
        }],
    }
    admin1 = {
        "type": "FeatureCollection",
        "features": [{"id": "US-CA", "properties": {"id": "US-CA", "country": "US"}}],
    }
    with pytest.raises(ValueError, match="unknown country"):
        build_generator_artifacts(countries, admin1, [_generator(country="ZZ")])
    with pytest.raises(ValueError, match="unknown ADM1"):
        build_generator_artifacts(countries, admin1, [_generator(geographyId="US-NOPE")])
    with pytest.raises(ValueError, match="duplicate generator id"):
        build_generator_artifacts(countries, admin1, [_generator(), _generator()])
    with pytest.raises(ValueError, match="source IDs"):
        build_generator_artifacts(countries, admin1, [_generator(sourceIds=[])])
    with pytest.raises(ValueError, match="finite"):
        build_generator_artifacts(
            countries, admin1, [_generator(operatingCapacityMw=float("nan"))]
        )


def test_global_builder_rejects_unprovenanced_or_unknown_regional_energy() -> None:
    countries = {
        "type": "FeatureCollection",
        "features": [{
            "id": "US", "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {"id": "US"},
        }],
    }
    admin1 = {
        "type": "FeatureCollection",
        "features": [{"id": "US-CA", "properties": {"id": "US-CA", "country": "US"}}],
    }
    common = {
        "countries": countries,
        "admin1": admin1,
        "regions": {"type": "FeatureCollection", "features": []},
        "registry": {"sources": [], "assets": []},
        "generated_at": "2026-06-30T00:00:00Z",
    }
    with pytest.raises(ValueError, match="unknown ADM1"):
        build_global_snapshot_artifacts(
            **common,
            regional_energy={"US-NOPE": [_energy_forecast(year) for year in range(2026, 2032)]},
        )
    rows = [_energy_forecast(year) for year in range(2026, 2032)]
    rows[0]["sourceIds"] = []
    with pytest.raises(ValueError, match="source IDs"):
        build_global_snapshot_artifacts(**common, regional_energy={"US-CA": rows})


def test_generator_artifacts_are_deterministic_and_reconcile_capacity() -> None:
    countries = {"type": "FeatureCollection", "features": [{"id": "US", "properties": {"id": "US"}}]}
    admin1 = {
        "type": "FeatureCollection",
        "features": [
            {"id": "US-CA", "properties": {"id": "US-CA", "country": "US"}},
            {"id": "US-TX", "properties": {"id": "US-TX", "country": "US"}},
        ],
    }
    plants = [
        _generator(),
        _generator(
            id="plant-us-tx-wind", geographyId="US-TX", coordinates=[-99.0, 31.0],
            technologies=["wind"], operatingCapacityMw=200.0, plannedCapacityMw=0.0,
        ),
    ]
    forward = build_generator_artifacts(countries, admin1, plants)
    reverse = build_generator_artifacts(countries, admin1, list(reversed(plants)))

    assert forward == reverse
    overview = json.loads(forward["generator-overview.geojson"])
    shard = json.loads(forward["generators/US.geojson"])
    assert sum(feature["properties"]["capacityMw"] for feature in overview["features"]) == 350.0
    assert sum(
        feature["properties"]["operatingCapacityMw"]
        + feature["properties"]["plannedCapacityMw"]
        for feature in shard["features"]
    ) == 350.0
