from __future__ import annotations

from datetime import UTC, datetime
import json
import math
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from grid_scope.config import QLEVER_OSM_URL
from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState


OSM_POWER_SOURCE_ID = "openstreetmap-power"
OSM_POWER_LICENCE = "ODbL-1.0"
DEFAULT_MINIMUM_OSM_POWER_RECORDS = 50_000
_OSM_ELEMENT = re.compile(r"^https://www\.openstreetmap\.org/(node|way|relation)/(\d+)$")
_COORDINATE = re.compile(r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")

QLEVER_POWER_QUERY = """
PREFIX osmkey: <https://www.openstreetmap.org/wiki/Key:>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
SELECT DISTINCT ?element ?name ?operator ?owner ?geometry ?source ?output ?lifecycle
  ?location ?scale ?startDate ?wikidata ?wikipedia
WHERE {
  ?element osmkey:power "plant" .
  ?element geo:hasGeometry/geo:asWKT ?geometry .
  OPTIONAL { ?element osmkey:name ?name . }
  OPTIONAL { ?element osmkey:operator ?operator . }
  OPTIONAL { ?element osmkey:owner ?owner . }
  OPTIONAL { ?element <https://www.openstreetmap.org/wiki/Key:plant:source> ?source . }
  OPTIONAL { ?element <https://www.openstreetmap.org/wiki/Key:plant:output:electricity> ?output . }
  OPTIONAL { ?element osmkey:status ?lifecycle . }
  OPTIONAL { ?element osmkey:location ?location . }
  OPTIONAL { ?element osmkey:scale ?scale . }
  FILTER(!BOUND(?location) || LCASE(STR(?location)) NOT IN ("roof", "rooftop"))
  FILTER(!BOUND(?scale) || LCASE(STR(?scale)) NOT IN ("household", "residential", "domestic"))
  OPTIONAL { ?element osmkey:start_date ?startDate . }
  OPTIONAL { ?element osmkey:wikidata ?wikidata . }
  OPTIONAL { ?element osmkey:wikipedia ?wikipedia . }
}
""".strip()

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
    "gas": "gas",
    "natural gas": "gas",
    "coal": "coal",
    "oil": "oil",
    "biomass": "biomass",
    "geothermal": "geothermal",
}

_LIFECYCLE_ALIASES = {
    "": "operational",
    "operating": "operational",
    "operational": "operational",
    "construction": "under_construction",
    "under construction": "under_construction",
    "pre construction": "announced",
    "planned": "announced",
    "proposed": "announced",
    "retired": "retired",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "shelved": "shelved",
}


def _value(binding: dict[str, Any], key: str) -> str | None:
    value = binding.get(key, {}).get("value")
    cleaned = str(value).strip() if value is not None else ""
    return cleaned or None


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
    normalized = _key(value)
    lifecycle = _LIFECYCLE_ALIASES.get(normalized)
    if lifecycle is None:
        raise ValueError(f"unsupported OSM power lifecycle: {value}")
    return lifecycle


def _representative_coordinates(wkt: str) -> list[float]:
    pairs = [(float(lon), float(lat)) for lon, lat in _COORDINATE.findall(wkt)]
    if not pairs:
        raise ValueError(f"unsupported or malformed OSM coordinates: {wkt[:80]}")
    if wkt.lstrip().upper().startswith("POINT"):
        lon, lat = pairs[0]
    else:
        lon = (min(point[0] for point in pairs) + max(point[0] for point in pairs)) / 2
        lat = (min(point[1] for point in pairs) + max(point[1] for point in pairs)) / 2
    if not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError("OSM geometry produced invalid coordinates")
    return [round(lon, 6), round(lat, 6)]


def _capacity(value: str | None) -> tuple[dict[str, float] | None, str]:
    if value is None:
        return None, "unavailable"
    match = re.search(r"(-?\d[\d,.]*)\s*(kW|MW|GW)\b", value, re.IGNORECASE)
    if not match:
        return None, "unavailable"
    raw_amount = match.group(1)
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", raw_amount):
        raw_amount = raw_amount.replace(",", "")
    else:
        raw_amount = raw_amount.replace(",", ".")
    amount = float(raw_amount)
    unit = match.group(2).lower()
    capacity = amount / 1_000 if unit == "kw" else amount * 1_000 if unit == "gw" else amount
    if not math.isfinite(capacity) or capacity < 0 or capacity > 100_000:
        raise ValueError(f"impossible capacity: {capacity}")
    return {"low": capacity, "central": capacity, "high": capacity}, "reported"


def _is_household_or_rooftop(binding: dict[str, Any]) -> bool:
    location = _key(_value(binding, "location"))
    scale = _key(_value(binding, "scale"))
    return location in {"roof", "rooftop"} or scale in {
        "household", "residential", "domestic",
    }


def _utility_scale_basis(
    binding: dict[str, Any],
    *,
    element_type: str,
    capacity: dict[str, float] | None,
    lifecycle: str,
    plant_source: str | None,
) -> str | None:
    if _is_household_or_rooftop(binding):
        return None
    if capacity is not None:
        return "reported_capacity_at_least_1mw" if capacity["central"] >= 1 else None
    if lifecycle in {"under_construction", "announced"}:
        return "planned_or_construction_lifecycle"
    if (
        element_type in {"way", "relation"}
        and _value(binding, "name")
        and plant_source
    ):
        return "named_plant_geometry_with_source"
    if any(_value(binding, field) for field in ("owner", "operator", "wikidata")):
        return "ownership_or_external_identity"
    return None


def parse_qlever_power(payload: dict[str, Any], *, observed_at: str) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for binding in payload.get("results", {}).get("bindings", []):
        element_url = _value(binding, "element")
        match = _OSM_ELEMENT.fullmatch(element_url or "")
        if match is None:
            raise ValueError(f"invalid OSM element URL: {element_url}")
        element_type, element_id = match.groups()
        capacity, capacity_kind = _capacity(_value(binding, "output"))
        raw_source = _value(binding, "source")
        raw_status = _value(binding, "lifecycle")
        lifecycle = _lifecycle(raw_status)
        utility_scale_basis = _utility_scale_basis(
            binding,
            element_type=element_type,
            capacity=capacity,
            lifecycle=lifecycle,
            plant_source=raw_source,
        )
        if utility_scale_basis is None:
            continue
        osm_reference = f"{element_type}/{element_id}"
        external_ids = {"osm": osm_reference}
        for key in ("wikidata", "wikipedia"):
            value = _value(binding, key)
            if value:
                external_ids[key] = value
        record = {
            "id": f"osm-power-{element_type}-{element_id}",
            "name": _value(binding, "name") or f"Mapped power plant · OSM {element_id}",
            "category": "power_generation",
            "technology": _technology(raw_source),
            "primaryFuel": raw_source,
            "secondaryFuel": None,
            "lifecycle": lifecycle,
            "rawStatus": raw_status,
            "utilityScaleBasis": utility_scale_basis,
            "capacityMw": capacity,
            "capacityValueKind": capacity_kind,
            "plantId": f"osm-power-{element_type}-{element_id}",
            "unitId": None,
            "externalIds": external_ids,
            "coordinates": _representative_coordinates(_value(binding, "geometry") or ""),
            "owner": _value(binding, "owner"),
            "operator": _value(binding, "operator"),
            "startDate": _value(binding, "startDate"),
            "sourceIds": [OSM_POWER_SOURCE_ID],
            "sourceType": "community_mapped",
            "sourceUrl": element_url,
            "licence": OSM_POWER_LICENCE,
            "updatedAt": observed_at,
            "sourceTags": {
                key: value["value"]
                for key, value in binding.items()
                if isinstance(value, dict) and value.get("value") is not None
            },
        }
        records[record["id"]] = record
    return list(records.values())


class OsmPowerConnector:
    source_id = "osm_power"

    def __init__(
        self,
        url: str = QLEVER_OSM_URL,
        *,
        minimum_records: int = DEFAULT_MINIMUM_OSM_POWER_RECORDS,
    ) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("QLever endpoint must be publicly addressable")
        if minimum_records < 0:
            raise ValueError("minimum OSM power record coverage cannot be negative")
        self.url = url
        self.minimum_records = minimum_records

    def fetch(self, client: httpx.Client, *, now: datetime | None = None) -> ConnectorResult:
        checked_at = now or datetime.now(UTC)
        response = client.post(
            self.url,
            content=QLEVER_POWER_QUERY,
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/sparql-query",
                "User-Agent": "Wattlas/1.0 (https://github.com/ad1tyagupta/wattlas)",
            },
        )
        response.raise_for_status()
        records = parse_qlever_power(
            response.json(), observed_at=checked_at.isoformat().replace("+00:00", "Z")
        )
        if len(records) < self.minimum_records:
            raise ValueError(
                f"too few OSM power records: {len(records)} < {self.minimum_records}"
            )
        body = json.dumps(
            {
                "source": OSM_POWER_SOURCE_ID,
                "licence": OSM_POWER_LICENCE,
                "attribution": "© OpenStreetMap contributors",
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
