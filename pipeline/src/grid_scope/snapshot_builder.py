from __future__ import annotations

import json
from math import log1p
from typing import Any

from grid_scope.canonicalize import assign_asset_geography
from grid_scope.generator_artifacts import build_generator_artifacts
from grid_scope.scoring import lifecycle_timing_index, score_infrastructure_demand
from shapely.geometry import mapping, shape
from shapely.ops import unary_union


YEAR_FACTORS = {
    2026: 0.72,
    2027: 0.80,
    2028: 0.88,
    2029: 0.95,
    2030: 1.00,
    2031: 1.04,
}

ADM1_UPSTREAM_PROPERTIES = frozenset({
    "id", "name", "country", "level", "parentId", "peerLevel", "sourceId",
    "boundaryPerspective", "population",
})


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
        "powerBalance": None,
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
    compact_upstream: bool = False,
) -> dict[str, Any]:
    original = feature.get("properties") or {}
    if compact_upstream:
        original = {key: value for key, value in original.items() if key in ADM1_UPSTREAM_PROPERTIES}
    region_id = original.get("id") or feature.get("id")
    payload = _scoring_payload(assets)
    current = payload.pop("current")
    has_evidence = current["scores"]["infrastructureDemand"] is not None
    inherited_scores = original.get("scoresByYear") if not has_evidence else None
    if inherited_scores:
        payload["scoresByYear"] = inherited_scores
        payload["contributionsByYear"] = original.get("contributionsByYear", payload["contributionsByYear"])
        payload["categoryScoresByYear"] = {
            year: {
                "combined": scores,
                "data_centre": _empty_scores(),
                "water_infrastructure": _empty_scores(),
            }
            for year, scores in inherited_scores.items()
        }
        has_evidence = inherited_scores.get("2030", {}).get("infrastructureDemand") is not None
    elif not assets:
        payload["scoresByYear"] = {"2030": _empty_scores()}
        payload["contributionsByYear"] = {"2030": []}
        payload["categoryScoresByYear"] = {
            "2030": {
                "combined": _empty_scores(),
                "data_centre": _empty_scores(),
                "water_infrastructure": _empty_scores(),
            }
        }
        payload["demandMwByYear"] = {
            "2030": {"combined": None, "data_centre": None, "water_infrastructure": None}
        }
    return {
        **feature,
        "id": region_id,
        "properties": {
            **original,
            "id": region_id,
            "scoreYear": 2030,
            "scores": payload["scoresByYear"]["2030"],
            **payload,
            "confidence": current["confidence"] if current["scores"]["infrastructureDemand"] is not None else original.get("confidence", 0),
            "coverage": 100 if has_evidence else 0,
            "valueKind": "estimated" if has_evidence else "unavailable",
            "updatedAt": generated_at,
            "contributions": payload["contributionsByYear"]["2030"],
            "sourceIds": sorted(
                {source for asset in assets for source in asset.get("sourceIds", [])}
                | set(original.get("sourceIds", []))
            ),
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
    regional_energy: dict[str, list[dict[str, Any]]] | None = None,
    power_plants: list[dict[str, Any]] | None = None,
    population_records: list[dict[str, Any]] | None = None,
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
    admin1_by_country: dict[str, list[dict[str, Any]]] = {}
    regions_by_country: dict[str, list[dict[str, Any]]] = {}
    for feature in admin1_features:
        admin1_by_country.setdefault((feature.get("properties") or {}).get("country", ""), []).append(feature)
    for feature in region_features:
        regions_by_country.setdefault((feature.get("properties") or {}).get("country", ""), []).append(feature)
    assets = [dict(asset) for asset in registry["assets"]]
    for asset in assets:
        country = asset.get("country", "")
        admin1_id = assign_asset_geography(asset, admin1_by_country.get(country, []))
        if admin1_id != asset.get("geographyId") and admin1_id != asset.get("country"):
            asset["admin1Id"] = admin1_id
        detailed_id = assign_asset_geography(asset, regions_by_country.get(country, []))
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
        if country_id == "IN" and admin1_features:
            india_geometry = admin1.get("metadata", {}).get("indiaCountryGeometry")
            if not india_geometry:
                india_shapes = [
                    shape(feature["geometry"])
                    for feature in admin1_features
                    if (feature.get("properties") or {}).get("country") == "IN"
                ]
                india_geometry = mapping(unary_union(india_shapes)) if india_shapes else None
            if india_geometry:
                geometry = india_geometry
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
        _enrich_regional_feature(feature, admin1_assets.get((feature.get("properties") or {}).get("id") or feature.get("id"), []), generated_at, compact_upstream=True)
        for feature in admin1_features
    ]
    enriched_regions = [
        _enrich_regional_feature(feature, region_assets.get((feature.get("properties") or {}).get("id") or feature.get("id"), []), generated_at)
        for feature in region_features
    ]

    known_admin1_ids = {
        str((feature.get("properties") or {}).get("id") or feature.get("id") or "").strip()
        for feature in admin1_features
    }
    population_by_region: dict[str, dict[str, Any]] = {}
    seen_population_keys: set[tuple[str, int]] = set()
    for raw in population_records or []:
        row = dict(raw)
        region_id = str(row.get("geographyId") or "").strip()
        if region_id not in known_admin1_ids:
            raise ValueError(f"population contains unknown ADM1: {region_id}")
        year = row.get("year")
        if isinstance(year, bool) or not isinstance(year, int) or not 2026 <= year <= 2031:
            raise ValueError(f"population for {region_id} has invalid year")
        key = (region_id, year)
        if key in seen_population_keys:
            raise ValueError(f"duplicate population geography/year: {region_id}/{year}")
        seen_population_keys.add(key)
        value = row.get("population")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"population for {region_id} must be a nonnegative integer")
        source_ids = row.get("sourceIds")
        if (
            not isinstance(source_ids, list)
            or not source_ids
            or any(not isinstance(item, str) or not item.strip() for item in source_ids)
            or not str(row.get("methodId") or "").strip()
        ):
            raise ValueError(f"population for {region_id} requires method and source IDs")
        if year == 2030:
            population_by_region[region_id] = row
    energy_by_region: dict[str, list[dict[str, Any]]] = {}
    for raw_region_id, raw_rows in sorted((regional_energy or {}).items()):
        region_id = str(raw_region_id).strip()
        if region_id not in known_admin1_ids:
            raise ValueError(f"regional energy contains unknown ADM1: {region_id}")
        if not isinstance(raw_rows, list):
            raise ValueError(f"regional energy for {region_id} must be a list")
        rows = [dict(row) for row in raw_rows]
        years = [row.get("year") for row in rows]
        if years != list(range(2026, 2032)):
            raise ValueError(
                f"regional energy for {region_id} requires ordered 2026-2031 records"
            )
        if any(
            row.get("geographyId") not in (None, region_id)
            for row in rows
        ):
            raise ValueError(f"regional energy geography ID mismatch for {region_id}")
        for row in rows:
            if not isinstance(row.get("methodId"), str) or not row["methodId"].strip():
                raise ValueError(f"regional energy for {region_id} requires a method ID")
            source_ids = row.get("sourceIds")
            if (
                not isinstance(source_ids, list)
                or not source_ids
                or any(not isinstance(value, str) or not value.strip() for value in source_ids)
            ):
                raise ValueError(f"regional energy for {region_id} requires source IDs")
            row["sourceIds"] = sorted({value.strip() for value in source_ids})
        energy_by_region[region_id] = rows

    for feature in enriched_admin1:
        properties = feature["properties"]
        region_id = properties["id"]
        population = population_by_region.get(region_id)
        if population:
            properties["population"] = population["population"]
            properties["populationYear"] = population["year"]
            properties["populationSourceYear"] = population.get("sourceYear")
            properties["populationValueKind"] = population.get("valueKind")
            properties["populationConfidence"] = population.get("confidence")
        rows = energy_by_region.get(region_id)
        properties["scores"].setdefault("powerBalance", None)
        for scores in properties.get("scoresByYear", {}).values():
            scores.setdefault("powerBalance", None)
        if rows:
            summary = next(row for row in rows if row["year"] == 2030)
            power_balance = summary.get("powerBalance") or {}
            score = power_balance.get("score")
            properties["scores"]["powerBalance"] = score
            properties.setdefault("scoresByYear", {}).setdefault("2030", _empty_scores())[
                "powerBalance"
            ] = score
            properties["powerBalanceYear"] = 2030
            properties["powerBalanceCoverage"] = power_balance.get(
                "coverage", summary.get("coverage")
            )
            properties["powerBalanceValueKind"] = summary.get("valueKind")

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
    generator_artifacts = build_generator_artifacts(
        countries, admin1, power_plants or []
    )
    artifacts = {
        "countries.geojson": json.dumps(country_collection, separators=(",", ":"), ensure_ascii=False).encode(),
        "admin1.geojson": json.dumps({"type": "FeatureCollection", "metadata": {key: value for key, value in admin1.get("metadata", {}).items() if key != "indiaCountryGeometry"}, "features": enriched_admin1}, separators=(",", ":"), ensure_ascii=False).encode(),
        "regions.geojson": json.dumps({"type": "FeatureCollection", "features": enriched_regions}, separators=(",", ":"), ensure_ascii=False).encode(),
        "assets.geojson": json.dumps({"type": "FeatureCollection", "features": asset_features}, separators=(",", ":"), ensure_ascii=False).encode(),
        "regional-energy.json": json.dumps(
            energy_by_region,
            separators=(",", ":"),
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ).encode(),
        "evidence.json": json.dumps({"sources": registry["sources"], "claims": claims}, separators=(",", ":"), ensure_ascii=False).encode(),
    }
    artifacts.update(generator_artifacts)
    return artifacts
