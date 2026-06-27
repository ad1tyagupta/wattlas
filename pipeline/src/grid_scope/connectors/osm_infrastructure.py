from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState


OSM_SOURCE_ID = "openstreetmap-infrastructure"
_OSM_ELEMENT = re.compile(r"^https://www\.openstreetmap\.org/(node|way|relation)/(\d+)$")
_COORDINATE = re.compile(r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")

QLEVER_INFRASTRUCTURE_QUERY = """
PREFIX osmkey: <https://www.openstreetmap.org/wiki/Key:>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
SELECT DISTINCT ?element ?name ?operator ?owner ?website ?facilityRef ?geometry ?category ?lifecycle
  ?openingDate ?startDate ?street ?houseNumber ?city ?state ?postcode ?countryAddress
  ?power ?wikidata ?wikipedia
WHERE {
  {
    ?element osmkey:telecom "data_center" .
    BIND("data_centre" AS ?category)
    BIND("operational" AS ?lifecycle)
  } UNION {
    ?element <https://www.openstreetmap.org/wiki/Key:construction:telecom> "data_center" .
    BIND("data_centre" AS ?category)
    BIND("under_construction" AS ?lifecycle)
  } UNION {
    ?element osmkey:construction "data_center" .
    BIND("data_centre" AS ?category)
    BIND("under_construction" AS ?lifecycle)
  } UNION {
    ?element <https://www.openstreetmap.org/wiki/Key:proposed:telecom> "data_center" .
    BIND("data_centre" AS ?category)
    BIND("announced" AS ?lifecycle)
  } UNION {
    ?element osmkey:water_works "desalination" .
    BIND("water_infrastructure" AS ?category)
    BIND("operational" AS ?lifecycle)
  } UNION {
    ?element osmkey:man_made "desalination_plant" .
    BIND("water_infrastructure" AS ?category)
    BIND("operational" AS ?lifecycle)
  }
  ?element geo:hasGeometry/geo:asWKT ?geometry .
  OPTIONAL { ?element osmkey:name ?name . }
  OPTIONAL { ?element osmkey:operator ?operator . }
  OPTIONAL { ?element osmkey:owner ?owner . }
  OPTIONAL { ?element osmkey:website ?website . }
  OPTIONAL { ?element osmkey:ref ?facilityRef . }
  OPTIONAL { ?element osmkey:opening_date ?openingDate . }
  OPTIONAL { ?element osmkey:start_date ?startDate . }
  OPTIONAL { ?element <https://www.openstreetmap.org/wiki/Key:addr:street> ?street . }
  OPTIONAL { ?element <https://www.openstreetmap.org/wiki/Key:addr:housenumber> ?houseNumber . }
  OPTIONAL { ?element <https://www.openstreetmap.org/wiki/Key:addr:city> ?city . }
  OPTIONAL { ?element <https://www.openstreetmap.org/wiki/Key:addr:state> ?state . }
  OPTIONAL { ?element <https://www.openstreetmap.org/wiki/Key:addr:postcode> ?postcode . }
  OPTIONAL { ?element <https://www.openstreetmap.org/wiki/Key:addr:country> ?countryAddress . }
  OPTIONAL { ?element <https://www.openstreetmap.org/wiki/Key:data_center:power> ?power . }
  OPTIONAL { ?element osmkey:wikidata ?wikidata . }
  OPTIONAL { ?element osmkey:wikipedia ?wikipedia . }
}
""".strip()


def _value(binding: dict[str, Any], key: str) -> str | None:
    value = binding.get(key, {}).get("value")
    return str(value).strip() if value is not None and str(value).strip() else None


def _representative_coordinates(wkt: str) -> list[float]:
    pairs = [(float(lon), float(lat)) for lon, lat in _COORDINATE.findall(wkt)]
    if not pairs:
        raise ValueError(f"unsupported or malformed OSM geometry: {wkt[:80]}")
    if wkt.lstrip().upper().startswith("POINT"):
        lon, lat = pairs[0]
    else:
        longitudes = [pair[0] for pair in pairs]
        latitudes = [pair[1] for pair in pairs]
        lon = (min(longitudes) + max(longitudes)) / 2
        lat = (min(latitudes) + max(latitudes)) / 2
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError("OSM geometry produced invalid coordinates")
    return [round(lon, 6), round(lat, 6)]


def _target_year(binding: dict[str, Any]) -> int | None:
    for key in ("openingDate", "startDate"):
        raw = _value(binding, key)
        match = re.search(r"\b(20\d{2})\b", raw or "")
        if match and 2026 <= int(match.group(1)) <= 2031:
            return int(match.group(1))
    return None


def parse_qlever_assets(payload: dict[str, Any], *, observed_at: str) -> list[dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    lifecycle_rank = {"operational": 0, "announced": 1, "under_construction": 2}
    for binding in payload.get("results", {}).get("bindings", []):
        element_url = _value(binding, "element")
        match = _OSM_ELEMENT.fullmatch(element_url or "")
        if not match:
            raise ValueError(f"invalid OSM element URL: {element_url}")
        element_type, element_id = match.groups()
        category = _value(binding, "category")
        lifecycle = _value(binding, "lifecycle") or "operational"
        if category not in {"data_centre", "water_infrastructure"}:
            raise ValueError(f"unsupported OSM infrastructure category: {category}")
        osm_ref = f"{element_type}/{element_id}"
        record_id = f"osm-{element_type}-{element_id}"
        fallback_type = "data centre" if category == "data_centre" else "desalination plant"
        record = {
            "id": record_id,
            "name": _value(binding, "name") or f"Mapped {fallback_type} · OSM {element_id}",
            "operator": _value(binding, "operator"),
            "geographyId": "UNASSIGNED",
            "category": category,
            "subtype": "other_data_centre" if category == "data_centre" else "desalination",
            "lifecycle": lifecycle,
            "targetYear": _target_year(binding),
            "coordinates": _representative_coordinates(_value(binding, "geometry") or ""),
            "locationPrecision": "exact",
            "valueKind": "observed",
            "sourceIds": [OSM_SOURCE_ID],
            "sourceType": "community_mapped",
            "sourceUrl": element_url,
            "externalIds": {"osm": osm_ref},
            "lastObservedAt": observed_at,
            "demandMw": None,
        }
        optional = {
            "owner": _value(binding, "owner"),
            "website": _value(binding, "website"),
            "facilityRef": _value(binding, "facilityRef"),
            "startDate": _value(binding, "startDate"),
            "openingDate": _value(binding, "openingDate"),
            "reportedPower": _value(binding, "power"),
        }
        record.update({key: value for key, value in optional.items() if value is not None})
        address = {
            "street": _value(binding, "street"),
            "houseNumber": _value(binding, "houseNumber"),
            "city": _value(binding, "city"),
            "state": _value(binding, "state"),
            "postcode": _value(binding, "postcode"),
            "country": _value(binding, "countryAddress"),
        }
        if any(address.values()):
            record["address"] = address
        for key in ("wikidata", "wikipedia"):
            value = _value(binding, key)
            if value:
                record["externalIds"][key] = value
        existing = normalized.get(record_id)
        if existing and lifecycle_rank.get(existing["lifecycle"], 0) > lifecycle_rank.get(lifecycle, 0):
            continue
        normalized[record_id] = record
    return list(normalized.values())


class OsmInfrastructureConnector:
    source_id = "osm_infrastructure"

    def __init__(self, url: str, *, minimum_data_centres: int = 3_500) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("QLever endpoint must be publicly addressable")
        self.url = url
        self.minimum_data_centres = minimum_data_centres

    def fetch(self, client: httpx.Client, *, now: datetime | None = None) -> ConnectorResult:
        checked_at = now or datetime.now(UTC)
        response = client.post(
            self.url,
            content=QLEVER_INFRASTRUCTURE_QUERY,
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/sparql-query",
                "User-Agent": "Wattlas/1.0 (https://github.com/ad1tyagupta/wattlas)",
            },
        )
        response.raise_for_status()
        assets = parse_qlever_assets(
            response.json(),
            observed_at=checked_at.isoformat().replace("+00:00", "Z"),
        )
        data_centres = sum(asset["category"] == "data_centre" for asset in assets)
        if data_centres < self.minimum_data_centres:
            raise ValueError(
                f"QLever returned too few data-centre records: {data_centres} < {self.minimum_data_centres}"
            )
        body = json.dumps(
            {
                "source": OSM_SOURCE_ID,
                "licence": "ODbL-1.0",
                "attribution": "© OpenStreetMap contributors",
                "assets": assets,
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
