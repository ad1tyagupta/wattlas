from __future__ import annotations

import json
from typing import Any

from grid_scope.scoring import score_infrastructure_demand


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
