from __future__ import annotations

import json
from math import log1p
from typing import Any

from grid_scope.canonicalize import assign_asset_geography
from grid_scope.scoring import lifecycle_timing_index, score_infrastructure_demand


YEAR_FACTORS = {
    2026: 0.72,
    2027: 0.80,
    2028: 0.88,
    2029: 0.95,
    2030: 1.00,
    2031: 1.04,
}


def _supporting_scores(drivers: dict[str, float]) -> tuple[int, int]:
    load = drivers["projected_load"]
    timing = drivers["delivery_timing"]
    shock = drivers["local_load_shock"]
    attractiveness = round(54 + 0.28 * load + 0.18 * timing - 0.24 * shock)
    risk = round(0.72 * shock + 0.18 * load + 0.10 * (100 - timing))
    return max(0, min(100, attractiveness)), max(0, min(100, risk))


def build_snapshot_artifacts(
    geometry: dict[str, Any],
    population: dict[str, int | None],
    curated: dict[str, Any],
    generated_at: str,
) -> dict[str, bytes]:
    clusters = {cluster["regionId"]: cluster for cluster in curated["clusters"]}
    region_features: list[dict[str, Any]] = []

    for source_feature in geometry.get("features", []):
        original = source_feature["properties"]
        region_id = original["NUTS_ID"]
        cluster = clusters.get(region_id)
        scores_by_year: dict[str, dict[str, int | None]] = {}
        contributions_by_year: dict[str, list[dict[str, Any]]] = {}

        if cluster:
            for year, factor in YEAR_FACTORS.items():
                values = {
                    key: min(100, round(value * factor, 1))
                    for key, value in cluster["drivers2030"].items()
                }
                demand = score_infrastructure_demand(
                    projected_load_index=values.get("projected_load"),
                    delivery_timing_index=values.get("delivery_timing"),
                    local_load_shock_index=values.get("local_load_shock"),
                    confidence=cluster["confidence"],
                    source_ids=cluster["sourceIds"],
                )
                attractiveness, risk = _supporting_scores(values)
                scores_by_year[str(year)] = {
                    "infrastructureDemand": demand.score,
                    "siteAttractiveness": attractiveness,
                    "systemRisk": risk,
                }
                contributions_by_year[str(year)] = [
                    {
                        **item.model_dump(by_alias=True, mode="json"),
                        "sourceIds": cluster["sourceIds"],
                    }
                    for item in demand.contributions
                ]
            value_kind = "estimated"
            confidence = cluster["confidence"]
            coverage = 100
            source_ids = cluster["sourceIds"]
        else:
            scores_by_year = {
                str(year): {
                    "infrastructureDemand": None,
                    "siteAttractiveness": None,
                    "systemRisk": None,
                }
                for year in YEAR_FACTORS
            }
            contributions_by_year = {str(year): [] for year in YEAR_FACTORS}
            value_kind = "unavailable"
            confidence = 0
            coverage = 0
            source_ids = []

        region_features.append(
            {
                "type": "Feature",
                "id": region_id,
                "geometry": source_feature["geometry"],
                "properties": {
                    "id": region_id,
                    "name": original.get("NAME_LATN") or original.get("NUTS_NAME") or region_id,
                    "country": original.get("CNTR_CODE", region_id[:2]),
                    "scoreYear": 2030,
                    "scores": scores_by_year["2030"],
                    "scoresByYear": scores_by_year,
                    "confidence": confidence,
                    "coverage": coverage,
                    "valueKind": value_kind,
                    "updatedAt": generated_at,
                    "contributions": contributions_by_year["2030"],
                    "contributionsByYear": contributions_by_year,
                    "sourceIds": source_ids,
                    "population": population.get(region_id),
                    "clusterId": cluster["id"] if cluster else None,
                },
            }
        )

    project_features = [
        {
            "type": "Feature",
            "id": cluster["id"],
            "geometry": {"type": "Point", "coordinates": cluster["coordinates"]},
            "properties": {
                "id": cluster["id"],
                "name": cluster["name"],
                "regionId": cluster["regionId"],
                "entityType": "cluster",
                "valueKind": "estimated",
                "sourceIds": cluster["sourceIds"],
                "confidence": cluster["confidence"],
            },
        }
        for cluster in curated["clusters"]
    ]

    claims = [
        {
            "id": f"{cluster['id']}-model-input",
            "entityId": cluster["id"],
            "summary": curated["modelNote"],
            "sourceIds": cluster["sourceIds"],
            "valueKind": "estimated",
            "observedAt": generated_at,
        }
        for cluster in curated["clusters"]
    ]

    return {
        "regions.geojson": json.dumps(
            {"type": "FeatureCollection", "features": region_features},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode(),
        "projects.geojson": json.dumps(
            {"type": "FeatureCollection", "features": project_features},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode(),
        "evidence.json": json.dumps(
            {"sources": curated["sources"], "claims": claims},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode(),
    }


def _empty_scores() -> dict[str, int | None]:
    return {
        "infrastructureDemand": None,
        "siteAttractiveness": None,
        "systemRisk": None,
    }


def _asset_confidence(asset: dict[str, Any]) -> int:
    precision = asset.get("locationPrecision")
    value_kind = asset.get("valueKind")
    score = {"exact": 78, "city_centroid": 68, "region_centroid": 56}.get(precision, 50)
    if value_kind == "reported":
        score += 8
    if len(asset.get("sourceIds", [])) > 1:
        score += 6
    return min(100, score)


def _score_assets(assets: list[dict[str, Any]], year: int) -> dict[str, Any]:
    active = [
        asset
        for asset in assets
        if asset.get("lifecycle") in {"announced", "planning_filed", "permitted", "under_construction"}
        and asset.get("demandMw") is not None
        and (asset.get("targetYear") is None or asset.get("targetYear") <= year)
    ]
    if not active:
        return {
            "scores": _empty_scores(),
            "contributions": [],
            "demandMw": None,
            "sourceIds": [],
            "confidence": 0,
        }

    central_mw = sum((asset.get("demandMw") or {}).get("central", 0) for asset in active)
    low_mw = sum((asset.get("demandMw") or {}).get("low", 0) for asset in active)
    high_mw = sum((asset.get("demandMw") or {}).get("high", 0) for asset in active)
    projected_load = min(100, round(100 * log1p(central_mw) / log1p(5_000), 1))
    weighted_timing = sum(
        lifecycle_timing_index(asset["lifecycle"], asset.get("targetYear"))
        * max(1, (asset.get("demandMw") or {}).get("central", 0))
        for asset in active
    ) / sum(max(1, (asset.get("demandMw") or {}).get("central", 0)) for asset in active)
    local_shock = min(100, round(projected_load * 0.72 + 8, 1))
    source_ids = sorted({source_id for asset in active for source_id in asset.get("sourceIds", [])})
    demand = score_infrastructure_demand(
        projected_load_index=projected_load,
        delivery_timing_index=weighted_timing,
        local_load_shock_index=local_shock,
        source_ids=source_ids,
    )
    attractiveness, risk = _supporting_scores(
        {
            "projected_load": projected_load,
            "delivery_timing": weighted_timing,
            "local_load_shock": local_shock,
        }
    )
    confidence = round(sum(_asset_confidence(asset) for asset in active) / len(active))
    return {
        "scores": {
            "infrastructureDemand": demand.score,
            "siteAttractiveness": attractiveness,
            "systemRisk": risk,
        },
        "contributions": [
            item.model_dump(by_alias=True, mode="json") for item in demand.contributions
        ],
        "demandMw": {
            "low": round(low_mw, 2),
            "central": round(central_mw, 2),
            "high": round(high_mw, 2),
        },
        "sourceIds": source_ids,
        "confidence": confidence,
    }


def _asset_summary(assets: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(assets),
        "operational": sum(asset.get("lifecycle") == "operational" for asset in assets),
        "planned": sum(asset.get("lifecycle") in {"announced", "planning_filed", "permitted", "under_construction"} for asset in assets),
        "dataCentres": sum(asset.get("category") == "data_centre" for asset in assets),
        "waterInfrastructure": sum(asset.get("category") == "water_infrastructure" for asset in assets),
        "officialVerified": sum(asset.get("sourceType", "official_verified") == "official_verified" for asset in assets),
        "communityMapped": sum(asset.get("sourceType") == "community_mapped" for asset in assets),
    }


def _scoring_payload(assets: list[dict[str, Any]]) -> dict[str, Any]:
    category_scores_by_year: dict[str, dict[str, dict[str, int | None]]] = {}
    scores_by_year: dict[str, dict[str, int | None]] = {}
    contributions_by_year: dict[str, list[dict[str, Any]]] = {}
    demand_by_year: dict[str, dict[str, dict[str, float] | None]] = {}
    combined_by_year: dict[int, dict[str, Any]] = {}
    for year in YEAR_FACTORS:
        data_centres = [asset for asset in assets if asset["category"] == "data_centre"]
        water = [asset for asset in assets if asset["category"] == "water_infrastructure"]
        category_results = {
            "combined": _score_assets(assets, year),
            "data_centre": _score_assets(data_centres, year),
            "water_infrastructure": _score_assets(water, year),
        }
        combined_by_year[year] = category_results["combined"]
        category_scores_by_year[str(year)] = {key: value["scores"] for key, value in category_results.items()}
        scores_by_year[str(year)] = category_results["combined"]["scores"]
        contributions_by_year[str(year)] = category_results["combined"]["contributions"]
        demand_by_year[str(year)] = {key: value["demandMw"] for key, value in category_results.items()}
    return {
        "categoryScoresByYear": category_scores_by_year,
        "scoresByYear": scores_by_year,
        "contributionsByYear": contributions_by_year,
        "demandMwByYear": demand_by_year,
        "current": combined_by_year[2030],
    }


def _enrich_regional_feature(
    feature: dict[str, Any],
    assets: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    original = feature.get("properties") or {}
    region_id = original.get("id") or feature.get("id")
    payload = _scoring_payload(assets)
    current = payload.pop("current")
    has_evidence = current["scores"]["infrastructureDemand"] is not None
    return {
        **feature,
        "id": region_id,
        "properties": {
            **original,
            "id": region_id,
            "scoreYear": 2030,
            "scores": payload["scoresByYear"]["2030"],
            **payload,
            "confidence": current["confidence"] if has_evidence else 0,
            "coverage": 100 if has_evidence else 0,
            "valueKind": "estimated" if has_evidence else "unavailable",
            "updatedAt": generated_at,
            "contributions": payload["contributionsByYear"]["2030"],
            "sourceIds": sorted({source for asset in assets for source in asset.get("sourceIds", [])}),
            "assetCount": len(assets),
            "assetSummary": _asset_summary(assets),
        },
    }


def build_global_snapshot_artifacts(
    *,
    countries: dict[str, Any],
    admin1: dict[str, Any] | None = None,
    regions: dict[str, Any],
    registry: dict[str, Any],
    generated_at: str,
) -> dict[str, bytes]:
    admin1 = admin1 or {"type": "FeatureCollection", "features": []}
    region_features = [
        {
            **feature,
            "properties": {
                **(feature.get("properties") or {}),
                "level": (feature.get("properties") or {}).get("level", "admin_2"),
                "parentId": (feature.get("properties") or {}).get("parentId", (feature.get("properties") or {}).get("country")),
                "peerLevel": (feature.get("properties") or {}).get("peerLevel", "admin_2"),
            },
        }
        for feature in regions.get("features", [])
    ]
    admin1_features = admin1.get("features", [])
    assets = [dict(asset) for asset in registry["assets"]]
    for asset in assets:
        admin1_id = assign_asset_geography(asset, admin1_features)
        if admin1_id != asset.get("geographyId") and admin1_id != asset.get("country"):
            asset["admin1Id"] = admin1_id
        detailed_id = assign_asset_geography(asset, region_features)
        if detailed_id != asset.get("geographyId") and detailed_id != asset.get("country"):
            asset["geographyId"] = detailed_id
        elif asset.get("admin1Id"):
            asset["geographyId"] = asset["admin1Id"]
    assets_by_country: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        assets_by_country.setdefault(asset["country"], []).append(asset)

    country_features: list[dict[str, Any]] = []
    for source_feature in countries.get("features", []):
        original = source_feature["properties"]
        country_id = original["id"]
        country_assets = assets_by_country.get(country_id, [])
        payload = _scoring_payload(country_assets)
        current = payload.pop("current")
        scores_by_year = payload["scoresByYear"]
        contributions_by_year = payload["contributionsByYear"]
        has_evidence = current["scores"]["infrastructureDemand"] is not None
        asset_summary = _asset_summary(country_assets)
        geometry = source_feature["geometry"]
        country_properties = dict(original)
        if country_id == "IN" and admin1.get("metadata", {}).get("indiaCountryGeometry"):
            geometry = admin1["metadata"]["indiaCountryGeometry"]
            country_properties["boundaryPerspective"] = admin1["metadata"].get("indiaBoundaryPerspective", "Government of India")
        country_features.append(
            {
                "type": "Feature",
                "id": country_id,
                "geometry": geometry,
                "properties": {
                    **country_properties,
                    "scoreYear": 2030,
                    "scores": scores_by_year["2030"],
                    "scoresByYear": scores_by_year,
                    "categoryScoresByYear": payload["categoryScoresByYear"],
                    "demandMwByYear": payload["demandMwByYear"],
                    "confidence": current["confidence"] if has_evidence else 0,
                    "coverage": 100 if has_evidence else 0,
                    "valueKind": "estimated" if has_evidence else "unavailable",
                    "updatedAt": generated_at,
                    "contributions": contributions_by_year["2030"],
                    "contributionsByYear": contributions_by_year,
                    "sourceIds": sorted({source for asset in country_assets for source in asset.get("sourceIds", [])}),
                    "assetCount": len(country_assets),
                    "assetSummary": asset_summary,
                },
            }
        )

    admin1_assets: dict[str, list[dict[str, Any]]] = {}
    region_assets: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        if asset.get("admin1Id"):
            admin1_assets.setdefault(asset["admin1Id"], []).append(asset)
        geography_id = asset.get("geographyId")
        if geography_id:
            region_assets.setdefault(geography_id, []).append(asset)
    enriched_admin1 = [
        _enrich_regional_feature(feature, admin1_assets.get((feature.get("properties") or {}).get("id") or feature.get("id"), []), generated_at)
        for feature in admin1_features
    ]
    enriched_regions = [
        _enrich_regional_feature(feature, region_assets.get((feature.get("properties") or {}).get("id") or feature.get("id"), []), generated_at)
        for feature in region_features
    ]

    asset_features = [
        {
            "type": "Feature",
            "id": asset["id"],
            "geometry": {"type": "Point", "coordinates": asset["coordinates"]},
            "properties": {
                **asset,
                "confidence": _asset_confidence(asset),
            },
        }
        for asset in assets
        if asset.get("coordinates") is not None
    ]
    claims = [
        {
            "id": f"{asset['id']}-demand-estimate",
            "entityId": asset["id"],
            "summary": registry.get("modelNote", "Public-source infrastructure demand estimate."),
            "sourceIds": asset["sourceIds"],
            "valueKind": asset["valueKind"],
            "observedAt": generated_at,
        }
        for asset in assets
    ]
    country_collection = {
        "type": "FeatureCollection",
        "metadata": countries.get("metadata", {}),
        "features": country_features,
    }
    return {
        "countries.geojson": json.dumps(country_collection, separators=(",", ":"), ensure_ascii=False).encode(),
        "admin1.geojson": json.dumps({"type": "FeatureCollection", "metadata": admin1.get("metadata", {}), "features": enriched_admin1}, separators=(",", ":"), ensure_ascii=False).encode(),
        "regions.geojson": json.dumps({"type": "FeatureCollection", "features": enriched_regions}, separators=(",", ":"), ensure_ascii=False).encode(),
        "assets.geojson": json.dumps({"type": "FeatureCollection", "features": asset_features}, separators=(",", ":"), ensure_ascii=False).encode(),
        "evidence.json": json.dumps({"sources": registry["sources"], "claims": claims}, separators=(",", ":"), ensure_ascii=False).encode(),
    }
