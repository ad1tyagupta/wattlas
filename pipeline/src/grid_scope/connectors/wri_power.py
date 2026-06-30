from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
import math
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from grid_scope.config import WRI_POWER_URL
from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState


WRI_SOURCE_ID = "wri-global-power-plant-database"
WRI_LICENCE = "CC-BY-4.0"
DEFAULT_MINIMUM_WRI_RECORDS = 30_000
_MAX_PLAUSIBLE_CAPACITY_MW = 100_000

_TECHNOLOGY_ALIASES = {
    "photovoltaic": "solar",
    "solar": "solar",
    "onshore wind": "wind",
    "onshore_wind": "wind",
    "offshore wind": "wind",
    "wind": "wind",
    "hydro": "hydro",
    "hydroelectric": "hydro",
    "nuclear": "nuclear",
    "ccgt": "gas",
    "ocgt": "gas",
    "gas": "gas",
    "natural gas": "gas",
    "coal": "coal",
    "oil": "oil",
    "petroleum": "oil",
    "biomass": "biomass",
    "geothermal": "geothermal",
}

_LIFECYCLE_ALIASES = {
    "operating": "operational",
    "operational": "operational",
    "construction": "under_construction",
    "under construction": "under_construction",
    "pre construction": "announced",
    "planned": "announced",
    "retired": "retired",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "shelved": "shelved",
}


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _technology(value: Any) -> str:
    normalized = _key(value)
    if normalized in _TECHNOLOGY_ALIASES:
        return _TECHNOLOGY_ALIASES[normalized]
    for alias, technology in _TECHNOLOGY_ALIASES.items():
        if alias in normalized:
            return technology
    return "other"


def _lifecycle(value: Any) -> str:
    normalized = _key(value or "operational")
    lifecycle = _LIFECYCLE_ALIASES.get(normalized)
    if lifecycle is None:
        raise ValueError(f"unsupported WRI lifecycle: {value}")
    return lifecycle


def _number(value: Any, *, label: str) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(str(value).replace(",", ""))
    except ValueError as error:
        raise ValueError(f"invalid {label}: {value}") from error
    if not math.isfinite(number):
        raise ValueError(f"invalid {label}: {value}")
    return number


def _capacity(value: Any) -> tuple[dict[str, float] | None, str]:
    capacity = _number(value, label="capacity")
    if capacity is None:
        return None, "unavailable"
    if capacity < 0 or capacity > _MAX_PLAUSIBLE_CAPACITY_MW:
        raise ValueError(f"impossible capacity: {capacity}")
    return {"low": capacity, "central": capacity, "high": capacity}, "reported"


def _coordinates(latitude: Any, longitude: Any) -> list[float] | None:
    latitude = None if latitude is None or not str(latitude).strip() else latitude
    longitude = None if longitude is None or not str(longitude).strip() else longitude
    if latitude is None and longitude is None:
        return None
    if latitude is None or longitude is None:
        raise ValueError("malformed coordinates: latitude and longitude must both be present")
    lat = _number(latitude, label="coordinates")
    lon = _number(longitude, label="coordinates")
    assert lat is not None and lon is not None
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError(f"invalid coordinates: {lat}, {lon}")
    return [round(lon, 6), round(lat, 6)]


def _geojson_point_coordinates(geometry: Any) -> list[float] | None:
    if geometry is None:
        return None
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        raise ValueError("WRI GeoJSON fallback requires a GeoJSON Point geometry")
    coordinates = geometry.get("coordinates")
    if (
        not isinstance(coordinates, (list, tuple))
        or len(coordinates) < 2
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in coordinates
        )
    ):
        raise ValueError("WRI GeoJSON Point has malformed coordinates")
    lon, lat = (float(value) for value in coordinates[:2])
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError(f"invalid WRI GeoJSON Point coordinates: {lon}, {lat}")
    return [round(lon, 6), round(lat, 6)]


def _year(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    number = _number(value, label="commissioning year")
    assert number is not None
    year = int(number)
    if year < 1800 or year > 2100:
        raise ValueError(f"invalid commissioning year: {value}")
    return year


def parse_wri_power(
    payload: dict[str, Any] | list[dict[str, Any]],
    *,
    updated_at: str | None = None,
) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
        rows = payload["data"]
    elif isinstance(payload, dict) and isinstance(payload.get("features"), list):
        rows = []
        for feature in payload["features"]:
            if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
                raise ValueError("WRI GeoJSON feature lacks properties")
            row = dict(feature["properties"])
            row["_sourceGeometry"] = feature.get("geometry")
            rows.append(row)
    else:
        raise ValueError("unexpected WRI power payload")

    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        external_id = str(row.get("gppd_idnr") or row.get("id") or "").strip()
        name = str(row.get("name") or row.get("plant_name") or "").strip()
        if not external_id or not name:
            raise ValueError(f"WRI row {index} lacks plant ID or name")
        capacity, capacity_kind = _capacity(row.get("capacity_mw"))
        primary_fuel = row.get("primary_fuel")
        source_geometry = row.get("_sourceGeometry")
        geometry_coordinates = _geojson_point_coordinates(source_geometry)
        coordinates = _coordinates(row.get("latitude"), row.get("longitude"))
        if coordinates is None:
            coordinates = geometry_coordinates
        history: dict[str, float] = {}
        for key, value in row.items():
            match = re.fullmatch(r"generation_gwh_(\d{4})", str(key))
            generation = _number(value, label="generation") if match else None
            if match and generation is not None:
                if generation < 0:
                    raise ValueError(f"impossible generation: {generation}")
                history[match.group(1)] = generation
        history = dict(sorted(history.items()))
        secondary_fuels = [
            str(value).strip()
            for value in (row.get("other_fuel1"), row.get("other_fuel2"), row.get("other_fuel3"))
            if value is not None and str(value).strip()
        ]
        source_url = str(row.get("url") or row.get("source_url") or "").strip() or None
        records.append({
            "id": f"wri-plant-{external_id}",
            "name": name,
            "category": "power_generation",
            "technology": _technology(primary_fuel),
            "primaryFuel": str(primary_fuel).strip() if primary_fuel is not None else None,
            "secondaryFuel": secondary_fuels[0] if secondary_fuels else None,
            "secondaryFuels": secondary_fuels,
            "lifecycle": _lifecycle(row.get("status")),
            "rawStatus": row.get("status"),
            "capacityMw": capacity,
            "capacityValueKind": capacity_kind,
            "reportedGenerationGwh": (
                {
                    "low": list(history.values())[-1],
                    "central": list(history.values())[-1],
                    "high": list(history.values())[-1],
                }
                if history else None
            ),
            "generationHistoryGwh": history,
            "plantId": f"wri-plant-{external_id}",
            "unitId": None,
            "externalIds": {"wri": external_id},
            "countryIso3": row.get("country"),
            "country": row.get("country_long"),
            "coordinates": coordinates,
            "sourceGeometry": source_geometry,
            "owner": row.get("owner"),
            "operator": row.get("operator"),
            "commissioningYear": _year(row.get("commissioning_year")),
            "sourceIds": [WRI_SOURCE_ID],
            "sourceType": "research_verified",
            "sourceUrl": source_url,
            "licence": WRI_LICENCE,
            "updatedAt": updated_at or row.get("updated_at"),
            "sourceRecord": {
                key: value for key, value in row.items() if key != "_sourceGeometry"
            },
        })
    return records


class WriPowerConnector:
    source_id = "wri_power"

    def __init__(
        self,
        url: str | None = WRI_POWER_URL,
        *,
        minimum_records: int = DEFAULT_MINIMUM_WRI_RECORDS,
    ) -> None:
        if minimum_records < 0:
            raise ValueError("minimum WRI record coverage cannot be negative")
        if url is not None:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("WRI resource URL must be publicly addressable")
        self.url = url
        self.minimum_records = minimum_records

    def fetch(self, client: httpx.Client, *, now: datetime | None = None) -> ConnectorResult:
        checked_at = now or datetime.now(UTC)
        if self.url is None:
            return ConnectorResult(
                source_id=self.source_id,
                state=ConnectorState.NOT_CONFIGURED,
                payload=None,
                message="Set WRI_POWER_URL to a reusable public WRI resource.",
            )
        response = client.get(self.url)
        response.raise_for_status()
        release_bytes = response.content
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise ValueError("WRI resource must be JSON") from error
        payload_updated_at = None
        if isinstance(payload, dict):
            payload_updated_at = payload.get("updatedAt") or payload.get("updated_at")
        release_updated_at = (
            payload_updated_at
            or response.headers.get("last-modified")
        )
        records = parse_wri_power(payload, updated_at=release_updated_at)
        if len(records) < self.minimum_records:
            raise ValueError(
                f"too few WRI power records: {len(records)} < {self.minimum_records}"
            )
        body = json.dumps(
            {
                "source": WRI_SOURCE_ID,
                "sourceUrl": self.url,
                "licence": WRI_LICENCE,
                "upstreamChecksumSha256": sha256(release_bytes).hexdigest(),
                "records": records,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return ConnectorResult(
            source_id=self.source_id,
            state=ConnectorState.CURRENT,
            payload=FetchPayload(
                source_id=self.source_id,
                retrieved_at=checked_at,
                media_type="application/json",
                body=body,
            ),
        )
