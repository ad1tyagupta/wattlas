from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Any, Iterable

from grid_scope.canonicalize import (
    GeographyIndex,
    _distance_km,
    build_geography_index,
    canonical_identifier,
    matching_asset_geographies,
    normalize_external_ids,
    normalize_source_ids,
)


SOURCE_RANK = {
    "official_verified": 4,
    "research_verified": 3,
    "community_mapped": 2,
    "modelled": 1,
}

_VALUE_KIND_RANK = {
    "unavailable": 0,
    "inherited": 1,
    "estimated": 2,
    "observed": 3,
    "reported": 3,
}
_TECHNOLOGIES = {
    "solar",
    "wind",
    "hydro",
    "nuclear",
    "gas",
    "coal",
    "oil",
    "biomass",
    "geothermal",
    "other",
}
_GENERIC_PLANT_WORDS = {
    "electric",
    "electricity",
    "generating",
    "generation",
    "plant",
    "power",
    "project",
    "station",
}
_UNIT_ID_NAMESPACES = {"gemunit", "unit", "unitid", "officialunit"}
_OPERATING_LIFECYCLES = {"operational"}
_PLANNED_LIFECYCLES = {"announced", "planning_filed", "permitted", "under_construction"}

_FIELD_KIND_NAMES = {
    "capacityMw": "capacityValueKind",
    "dependableCapacityMw": "dependableCapacityValueKind",
    "annualGenerationGwh": "generationValueKind",
}
_COMPANION_KIND_FIELDS = set(_FIELD_KIND_NAMES.values())
_LOCATION_FIELDS = {
    "canonicalCountryKey",
    "coordinates",
    "country",
    "geographyId",
    "locationPrecision",
}
_PRECISION_RANK = {"region_centroid": 0, "city_centroid": 1, "exact": 2}
_RECORD_ANCHOR_PRIORITY = {
    "gemunit": 0,
    "gemplant": 1,
    "wri": 2,
    "osm": 3,
    "wikidata": 4,
    "officialunit": 5,
    "official": 6,
    "unit": 7,
    "unitid": 7,
    "wikipedia": 8,
    "unitref": 20,
    "plantref": 21,
}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _namespace_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _normalized_text(value: Any, aliases: dict[str, str]) -> str:
    tokens = _key(value).split()
    expanded: list[str] = []
    for token in tokens:
        expanded.extend(aliases.get(token, token).split())
    return " ".join(expanded)


def _name_tokens(value: Any, aliases: dict[str, str]) -> set[str]:
    return {
        token
        for token in _normalized_text(value, aliases).split()
        if token not in _GENERIC_PLANT_WORDS
    }


def _name_signature(value: Any, aliases: dict[str, str]) -> tuple[str, ...]:
    return tuple(sorted(_name_tokens(value, aliases)))


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _normalize_lifecycle(record: dict[str, Any]) -> tuple[str, str | None]:
    source_lifecycle = _key(record.get("lifecycle"))
    raw_status = _clean_text(record.get("rawStatus"))
    aliases = {
        "operating": "operational",
        "operational": "operational",
        "construction": "under_construction",
        "under construction": "under_construction",
        "planned": "announced",
        "proposed": "announced",
        "pre construction": "announced",
        "announced": "announced",
        "planning filed": "planning_filed",
        "permitted": "permitted",
        "mothballed": "paused",
        "mothball": "paused",
        "paused": "paused",
        "shelved": "paused",
        "inactive": "paused",
        "retired": "cancelled",
        "decommissioned": "cancelled",
        "cancelled": "cancelled",
        "canceled": "cancelled",
    }
    canonical = aliases.get(source_lifecycle)
    if canonical is None:
        raise ValueError(f"unsupported power-plant lifecycle: {record.get('lifecycle')}")
    if source_lifecycle in {"shelved", "retired", "decommissioned", "mothballed", "mothball"}:
        raw_status = raw_status or source_lifecycle
    return canonical, raw_status


def _normalize_range(value: Any, *, field: str) -> dict[str, float] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number or range")
    if isinstance(value, (int, float)):
        number = float(value)
        values = {"low": number, "central": number, "high": number}
    elif isinstance(value, dict):
        try:
            values = {part: float(value[part]) for part in ("low", "central", "high")}
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{field} must contain numeric low, central, and high values") from error
    else:
        raise ValueError(f"{field} must be a number or range")
    if any(not math.isfinite(number) for number in values.values()):
        raise ValueError(f"{field} must contain only finite numbers")
    if any(number < 0 for number in values.values()):
        raise ValueError(f"{field} cannot be negative")
    if not values["low"] <= values["central"] <= values["high"]:
        raise ValueError(f"{field} must satisfy low <= central <= high")
    return values


def _country_values(record: dict[str, Any]) -> list[str]:
    return [
        value
        for field in ("countryIso3", "countryIso2", "country")
        if (value := canonical_identifier(record.get(field))) is not None
    ]


def _country_component_key(
    values: set[str],
    *,
    iso3_values: set[str] | None = None,
    iso2_values: set[str] | None = None,
) -> str:
    iso3 = sorted(value.upper() for value in (iso3_values or set()) if value in values)
    if iso3:
        return iso3[0]
    iso2 = sorted(value.upper() for value in (iso2_values or set()) if value in values)
    if iso2:
        return iso2[0]
    return sorted(_key(value) for value in values if _key(value))[0]


def _build_country_aliases(
    records: list[dict[str, Any]],
    geographies: list[dict] | None,
    overrides: dict[str, str] | None,
) -> dict[str, str]:
    links: dict[str, set[str]] = {}
    explicit_iso3: set[str] = set()
    explicit_iso2: set[str] = set()

    def link(values: Iterable[str]) -> None:
        normalized = {_key(value) for value in values if _key(value)}
        for value in normalized:
            links.setdefault(value, set()).update(normalized)

    for record in records:
        link(_country_values(record))
        for field, target, length in (
            ("countryIso3", explicit_iso3, 3),
            ("countryIso2", explicit_iso2, 2),
        ):
            value = canonical_identifier(record.get(field))
            if value is not None and len(value) == length and value.isalpha():
                target.add(_key(value))
        country = canonical_identifier(record.get("country"))
        if country is not None and country.isalpha():
            if len(country) == 2:
                explicit_iso2.add(_key(country))
            elif len(country) == 3 and country == country.upper():
                explicit_iso3.add(_key(country))
    for feature in geographies or []:
        properties = feature.get("properties") or {}
        level = _key(properties.get("level"))
        fields = [
            "iso3",
            "ISO3",
            "countryIso3",
            "iso2",
            "ISO2",
            "countryIso2",
            "country",
            "parentId",
        ]
        if level == "country":
            fields.extend(["id", "name"])
        values = [
            value
            for field in fields
            if (value := canonical_identifier(properties.get(field))) is not None
        ]
        link(values)
        for field in ("iso3", "ISO3", "countryIso3"):
            value = canonical_identifier(properties.get(field))
            if value is not None and len(value) == 3 and value.isalpha():
                explicit_iso3.add(_key(value))
        for field in ("iso2", "ISO2", "countryIso2"):
            value = canonical_identifier(properties.get(field))
            if value is not None and len(value) == 2 and value.isalpha():
                explicit_iso2.add(_key(value))
        for field in ("country", "parentId"):
            country = canonical_identifier(properties.get(field))
            if country is not None and country.isalpha():
                if len(country) == 3:
                    explicit_iso3.add(_key(country))
                elif len(country) == 2:
                    explicit_iso2.add(_key(country))
    for alias, target in (overrides or {}).items():
        link([alias, target])
        clean_target = canonical_identifier(target)
        if clean_target is not None and clean_target.isalpha():
            if len(clean_target) == 3:
                explicit_iso3.add(_key(clean_target))
            elif len(clean_target) == 2:
                explicit_iso2.add(_key(clean_target))

    resolved: dict[str, str] = {}
    unseen = set(links)
    while unseen:
        seed = min(unseen)
        component: set[str] = set()
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            if current in component:
                continue
            component.add(current)
            frontier.extend(links.get(current, set()) - component)
        unseen -= component
        canonical = _country_component_key(
            component,
            iso3_values=explicit_iso3,
            iso2_values=explicit_iso2,
        )
        for value in component:
            resolved[value] = canonical
    return resolved


def _spatial_country(
    matches: list[dict[str, Any]],
    country_aliases: dict[str, str],
) -> tuple[str | None, str | None]:
    values: list[str] = []
    iso2_values: set[str] = set()
    for feature in matches:
        properties = feature.get("properties") or {}
        level = _key(properties.get("level"))
        for field in (
            "iso3",
            "ISO3",
            "countryIso3",
            "iso2",
            "ISO2",
            "countryIso2",
            "country",
            "parentId",
        ):
            value = canonical_identifier(properties.get(field))
            if value is not None:
                values.append(value)
        if level == "country":
            for value in (
                canonical_identifier(properties.get("id")),
                canonical_identifier(feature.get("id")),
            ):
                if value is not None:
                    values.append(value)
        for field in ("iso2", "ISO2", "countryIso2", "country", "parentId"):
            value = canonical_identifier(properties.get(field))
            if value is not None and len(value) == 2 and value.isalpha():
                iso2_values.add(value.upper())
        if level == "country":
            identifier = canonical_identifier(properties.get("id") or feature.get("id"))
            if identifier is not None and len(identifier) == 2 and identifier.isalpha():
                iso2_values.add(identifier.upper())
    canonical_keys = {
        country_aliases[_key(value)]
        for value in values
        if _key(value) in country_aliases
    }
    canonical = sorted(canonical_keys)[0] if canonical_keys else None
    country = sorted(iso2_values)[0] if iso2_values else canonical
    return canonical, country


def _normalize_record(
    record: dict[str, Any],
    country_aliases: dict[str, str],
    geographies: GeographyIndex | None,
) -> dict[str, Any]:
    normalized = deepcopy(record)
    record_id = canonical_identifier(normalized.get("id"))
    if record_id is None:
        raise ValueError("power-plant records require a finite nonblank ID")
    normalized["id"] = record_id
    for relationship_id in ("plantId", "unitId"):
        normalized[relationship_id] = canonical_identifier(normalized.get(relationship_id))

    normalized["category"] = "power_generation"
    technology = _key(normalized.get("technology")).replace(" ", "_") or "other"
    normalized["technology"] = technology if technology in _TECHNOLOGIES else "other"
    normalized["capacityMw"] = _normalize_range(normalized.get("capacityMw"), field="capacityMw")
    normalized["dependableCapacityMw"] = _normalize_range(
        normalized.get("dependableCapacityMw"), field="dependableCapacityMw"
    )
    annual_generation = normalized.get("annualGenerationGwh")
    if annual_generation is None and normalized.get("reportedGenerationGwh") is not None:
        annual_generation = normalized.get("reportedGenerationGwh")
        normalized.setdefault("generationValueKind", "reported")
    normalized["annualGenerationGwh"] = _normalize_range(
        annual_generation, field="annualGenerationGwh"
    )
    normalized.pop("reportedGenerationGwh", None)

    lifecycle, raw_status = _normalize_lifecycle(normalized)
    normalized["lifecycle"] = lifecycle
    if raw_status is not None:
        normalized["rawStatus"] = raw_status

    normalized["externalIds"] = normalize_external_ids(normalized.get("externalIds"))
    normalized["sourceIds"] = normalize_source_ids(normalized.get("sourceIds"))
    normalized["sourceType"] = normalized.get("sourceType") or "modelled"
    if normalized["sourceType"] not in SOURCE_RANK:
        raise ValueError(f"unsupported power-plant source type: {normalized['sourceType']}")
    normalized["valueKind"] = normalized.get("valueKind") or (
        normalized.get("capacityValueKind")
        if normalized.get("capacityMw") is not None
        else "observed"
    )
    normalized["capacityValueKind"] = normalized.get("capacityValueKind") or (
        normalized["valueKind"] if normalized.get("capacityMw") is not None else "unavailable"
    )
    if normalized.get("annualGenerationGwh") is not None:
        normalized["generationValueKind"] = (
            normalized.get("generationValueKind") or normalized["valueKind"]
        )

    fuels = {
        str(value).strip()
        for value in [normalized.get("secondaryFuel"), *(normalized.get("secondaryFuels") or [])]
        if value is not None and str(value).strip()
    }
    primary_fuel = _clean_text(normalized.get("primaryFuel"))
    if primary_fuel:
        fuels.discard(primary_fuel)
    preferred_secondary_fuel = _clean_text(normalized.get("secondaryFuel"))
    normalized["primaryFuel"] = primary_fuel
    normalized["secondaryFuels"] = sorted(fuels)
    normalized["secondaryFuel"] = (
        preferred_secondary_fuel
        if preferred_secondary_fuel in fuels
        else sorted(fuels)[0] if fuels else None
    )

    coordinates = normalized.get("coordinates")
    if coordinates is not None:
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
            raise ValueError("power-plant coordinates must contain longitude and latitude")
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
        if (
            not math.isfinite(longitude)
            or not math.isfinite(latitude)
            or not -180 <= longitude <= 180
            or not -90 <= latitude <= 90
        ):
            raise ValueError("power-plant coordinates must be finite WGS84 coordinates")
        normalized["coordinates"] = [longitude, latitude]
        normalized["locationPrecision"] = normalized.get("locationPrecision") or "exact"
    else:
        normalized["locationPrecision"] = normalized.get("locationPrecision") or "region_centroid"

    country_values = _country_values(normalized)
    country_alias = _key(country_values[0]) if country_values else ""
    record_iso3 = canonical_identifier(normalized.get("countryIso3"))
    record_iso2 = canonical_identifier(normalized.get("countryIso2"))
    normalized["canonicalCountryKey"] = country_aliases.get(
        country_alias,
        (
            _country_component_key(
                {_key(value) for value in country_values},
                iso3_values=(
                    {_key(record_iso3)}
                    if record_iso3 and len(record_iso3) == 3 and record_iso3.isalpha()
                    else set()
                ),
                iso2_values=(
                    {_key(record_iso2)}
                    if record_iso2 and len(record_iso2) == 2 and record_iso2.isalpha()
                    else set()
                ),
            )
            if country_values
            else ""
        ),
    )
    normalized["geographyId"] = (
        normalized.get("geographyId")
        or normalized.get("canonicalCountryKey")
        or "UNASSIGNED"
    )
    if geographies is not None:
        matches = matching_asset_geographies(normalized, geographies)
        if matches:
            best = matches[0]
            normalized["geographyId"] = (
                best.get("properties", {}).get("id")
                or best.get("id")
                or normalized["geographyId"]
            )
            spatial_country_key, spatial_country = _spatial_country(matches, country_aliases)
            if spatial_country_key is not None:
                normalized["canonicalCountryKey"] = spatial_country_key
            if spatial_country is not None:
                normalized["country"] = spatial_country

    normalized["aliases"] = sorted(
        {
            str(value).strip()
            for value in [
                *(normalized.get("aliases") or []),
                normalized.get("name"),
                normalized.get("plantName"),
            ]
            if value is not None and str(value).strip()
        }
    )
    normalized["evidence"] = sorted(
        [deepcopy(item) for item in normalized.get("evidence", []) if isinstance(item, dict)],
        key=_stable_json,
    )
    normalized.pop("subtype", None)
    return normalized


def _unit_record(record: dict[str, Any]) -> bool:
    return _present(record.get("unitId"))


def _country_key(record: dict[str, Any]) -> str:
    return str(record.get("canonicalCountryKey") or "")


def _external_identity_map(
    record: dict[str, Any],
    *,
    entity: bool,
) -> dict[str, str]:
    identities: dict[str, str] = {}
    for namespace, identifier in (record.get("externalIds") or {}).items():
        namespace_key = _namespace_key(namespace)
        if entity and _unit_record(record) and namespace_key not in _UNIT_ID_NAMESPACES:
            continue
        if not entity and namespace_key in _UNIT_ID_NAMESPACES:
            continue
        identities[namespace_key] = identifier
    return identities


def _plant_reference_namespace(record: dict[str, Any]) -> str:
    plant_id = str(record.get("plantId") or "").casefold()
    if plant_id.startswith("gem-"):
        return "plantref_gem"
    if plant_id.startswith("wri-"):
        return "plantref_wri"
    if plant_id.startswith("osm-"):
        return "plantref_osm"
    source_ids = record.get("sourceIds") or []
    source = _namespace_key(source_ids[0]) if source_ids else _namespace_key(record.get("sourceType"))
    return f"plantref_{source or 'unknown'}"


def _plant_identity_map(record: dict[str, Any]) -> dict[str, str]:
    identities = _external_identity_map(record, entity=False)
    plant_id = canonical_identifier(record.get("plantId"))
    if plant_id is not None:
        identities[_plant_reference_namespace(record)] = plant_id
    return identities


def _central_capacity(record: dict[str, Any]) -> float | None:
    capacity = record.get("capacityMw")
    return float(capacity["central"]) if isinstance(capacity, dict) else None


def _shared_identity(first: dict[str, str], second: dict[str, str]) -> bool:
    return any(
        identifier == second.get(namespace)
        for namespace, identifier in first.items()
        if namespace in second
    )


def _strong_fuzzy_duplicate(
    first: dict[str, Any],
    second: dict[str, Any],
    aliases: dict[str, str],
) -> bool:
    if _unit_record(first) != _unit_record(second):
        return False
    if _unit_record(first):
        if not _shared_identity(_plant_identity_map(first), _plant_identity_map(second)):
            return False
        first_unit_name = _normalized_text(first.get("name"), aliases)
        second_unit_name = _normalized_text(second.get("name"), aliases)
        if not first_unit_name or first_unit_name != second_unit_name:
            return False
        first_year = first.get("commissioningYear")
        second_year = second.get("commissioningYear")
        if first_year and second_year and first_year != second_year:
            return False
    if not _country_key(first) or _country_key(first) != _country_key(second):
        return False
    first_operator = _normalized_text(first.get("operator"), aliases)
    second_operator = _normalized_text(second.get("operator"), aliases)
    if not first_operator or first_operator != second_operator:
        return False
    first_coordinates = first.get("coordinates")
    second_coordinates = second.get("coordinates")
    if (
        not first_coordinates
        or not second_coordinates
        or _distance_km(first_coordinates, second_coordinates) > 5
    ):
        return False
    first_capacity = _central_capacity(first)
    second_capacity = _central_capacity(second)
    if first_capacity is None or second_capacity is None:
        return False
    if first_capacity == 0 or second_capacity == 0:
        if first_capacity != second_capacity:
            return False
    elif not 0.9 <= first_capacity / second_capacity <= 1.1:
        return False
    first_name = first.get("name") if _unit_record(first) else first.get("plantName") or first.get("name")
    second_name = second.get("name") if _unit_record(second) else second.get("plantName") or second.get("name")
    first_signature = _name_signature(first_name, aliases)
    second_signature = _name_signature(second_name, aliases)
    return bool(first_signature and first_signature == second_signature)


def _same_plant(first: dict[str, Any], second: dict[str, Any], aliases: dict[str, str]) -> bool:
    if _shared_identity(_plant_identity_map(first), _plant_identity_map(second)):
        return True
    if not _country_key(first) or _country_key(first) != _country_key(second):
        return False
    first_name = _name_signature(first.get("plantName") or first.get("name"), aliases)
    second_name = _name_signature(second.get("plantName") or second.get("name"), aliases)
    if not first_name or first_name != second_name:
        return False
    first_operator = _normalized_text(first.get("operator"), aliases)
    second_operator = _normalized_text(second.get("operator"), aliases)
    if not first_operator or first_operator != second_operator:
        return False
    first_coordinates = first.get("coordinates")
    second_coordinates = second.get("coordinates")
    return bool(
        first_coordinates
        and second_coordinates
        and _distance_km(first_coordinates, second_coordinates) <= 5
    )


@dataclass
class _ClusterSet:
    parents: list[int]
    identities: list[dict[str, set[str]]]
    countries: list[set[str]]
    kinds: list[set[str]]

    @classmethod
    def create(
        cls,
        records: list[dict[str, Any]],
        identity_getter: Any,
        *,
        track_kind: bool,
    ) -> "_ClusterSet":
        return cls(
            parents=list(range(len(records))),
            identities=[
                {namespace: {identifier} for namespace, identifier in identity_getter(record).items()}
                for record in records
            ],
            countries=[{_country_key(record)} if _country_key(record) else set() for record in records],
            kinds=[{"unit" if _unit_record(record) else "plant"} if track_kind else set() for record in records],
        )

    def find(self, index: int) -> int:
        if self.parents[index] != index:
            self.parents[index] = self.find(self.parents[index])
        return self.parents[index]

    def union_if_compatible(self, first: int, second: int) -> bool:
        first_root, second_root = self.find(first), self.find(second)
        if first_root == second_root:
            return True
        if self.kinds[first_root] and self.kinds[second_root] and self.kinds[first_root] != self.kinds[second_root]:
            return False
        if (
            self.countries[first_root]
            and self.countries[second_root]
            and self.countries[first_root] != self.countries[second_root]
        ):
            return False
        shared_namespaces = self.identities[first_root].keys() & self.identities[second_root].keys()
        if any(
            self.identities[first_root][namespace]
            != self.identities[second_root][namespace]
            for namespace in shared_namespaces
        ):
            return False
        lower, higher = sorted((first_root, second_root))
        self.parents[higher] = lower
        for namespace, identifiers in self.identities[higher].items():
            self.identities[lower].setdefault(namespace, set()).update(identifiers)
        self.countries[lower].update(self.countries[higher])
        self.kinds[lower].update(self.kinds[higher])
        return True


def _capacity_band(record: dict[str, Any]) -> int | None:
    capacity = _central_capacity(record)
    if capacity is None:
        return None
    if capacity == 0:
        return 0
    return int(math.floor(math.log(capacity) / math.log(1.1)))


def _spatial_cell(record: dict[str, Any]) -> tuple[int, int] | None:
    coordinates = record.get("coordinates")
    if not coordinates:
        return None
    return math.floor(float(coordinates[0])), math.floor(float(coordinates[1]))


def _fuzzy_base(
    record: dict[str, Any], aliases: dict[str, str], *, plant_group: bool
) -> tuple[str, str, set[str], tuple[int, int] | None, int | None]:
    country = _country_key(record)
    operator = _normalized_text(record.get("operator"), aliases)
    name = (
        record.get("plantName") or record.get("name")
        if plant_group
        else record.get("name") if _unit_record(record) else record.get("plantName") or record.get("name")
    )
    if not plant_group and _unit_record(record):
        normalized_unit_name = _normalized_text(name, aliases)
        name_tokens = {f"unit-name:{normalized_unit_name}"} if normalized_unit_name else set()
    else:
        signature = _name_signature(name, aliases)
        name_tokens = {"name-signature:" + "\x1f".join(signature)} if signature else set()
    return country, operator, name_tokens, _spatial_cell(record), _capacity_band(record)


def _candidate_keys(
    record: dict[str, Any], aliases: dict[str, str], *, plant_group: bool
) -> list[tuple[Any, ...]]:
    country, operator, name_tokens, cell, capacity_band = _fuzzy_base(
        record, aliases, plant_group=plant_group
    )
    if not country or not operator or not name_tokens or cell is None:
        return []
    kind = "plant-group" if plant_group else "unit" if _unit_record(record) else "plant"
    bands: list[int | None]
    if plant_group:
        bands = [None]
    elif capacity_band is None:
        return []
    else:
        bands = list(range(capacity_band - 2, capacity_band + 3))
    return [
        (country, kind, operator, token, cell[0] + dx, cell[1] + dy, band)
        for token in sorted(name_tokens)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for band in bands
    ]


def _insertion_keys(
    record: dict[str, Any], aliases: dict[str, str], *, plant_group: bool
) -> list[tuple[Any, ...]]:
    country, operator, name_tokens, cell, capacity_band = _fuzzy_base(
        record, aliases, plant_group=plant_group
    )
    if not country or not operator or not name_tokens or cell is None:
        return []
    if not plant_group and capacity_band is None:
        return []
    kind = "plant-group" if plant_group else "unit" if _unit_record(record) else "plant"
    band = None if plant_group else capacity_band
    return [
        (country, kind, operator, token, cell[0], cell[1], band)
        for token in sorted(name_tokens)
    ]


def _indexed_clusters(
    records: list[dict[str, Any]],
    aliases: dict[str, str],
    *,
    plant_group: bool,
) -> list[list[dict[str, Any]]]:
    identity_getter = _plant_identity_map if plant_group else lambda record: _external_identity_map(record, entity=True)
    groups = _ClusterSet.create(records, identity_getter, track_kind=not plant_group)
    exact_index: dict[tuple[str, str], set[int]] = {}
    fuzzy_index: dict[tuple[Any, ...], dict[int, int]] = {}

    def exact_roots(token: tuple[str, str]) -> set[int]:
        roots = {groups.find(candidate) for candidate in exact_index.get(token, set())}
        exact_index[token] = roots
        return roots

    def fuzzy_representatives(key: tuple[Any, ...]) -> dict[int, int]:
        representatives: dict[int, int] = {}
        for candidate in fuzzy_index.get(key, {}).values():
            representatives.setdefault(groups.find(candidate), candidate)
        fuzzy_index[key] = representatives
        return representatives

    for index, record in enumerate(records):
        identities = identity_getter(record)
        exact_candidates = {
            candidate
            for token in identities.items()
            for candidate in exact_roots(token)
        }
        for candidate in sorted(exact_candidates):
            groups.union_if_compatible(index, candidate)

        fuzzy_candidates = {
            candidate
            for key in _candidate_keys(record, aliases, plant_group=plant_group)
            for candidate in fuzzy_representatives(key).values()
        }
        for candidate in sorted(fuzzy_candidates):
            if groups.find(index) == groups.find(candidate):
                continue
            matches = (
                _same_plant(record, records[candidate], aliases)
                if plant_group
                else _strong_fuzzy_duplicate(record, records[candidate], aliases)
            )
            if matches:
                groups.union_if_compatible(index, candidate)

        for token in identities.items():
            roots = exact_roots(token)
            roots.add(groups.find(index))
        for key in _insertion_keys(record, aliases, plant_group=plant_group):
            representatives = fuzzy_representatives(key)
            representatives.setdefault(groups.find(index), index)

    clustered: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(records):
        clustered.setdefault(groups.find(index), []).append(record)
    return [clustered[root] for root in sorted(clustered)]


def _field_value_kind(record: dict[str, Any], field: str) -> str | None:
    kind_field = _FIELD_KIND_NAMES.get(field)
    if kind_field:
        return record.get(kind_field) or record.get("valueKind")
    return record.get("valueKind")


def _field_preference(record: dict[str, Any], field: str) -> tuple[int, int, int, str]:
    value_kind = _field_value_kind(record, field)
    value_rank = _VALUE_KIND_RANK.get(str(value_kind), 0) if field in _FIELD_KIND_NAMES else 0
    source_rank = SOURCE_RANK.get(record.get("sourceType"), 0)
    precision_rank = _PRECISION_RANK.get(record.get("locationPrecision"), -1)
    return value_rank, source_rank, precision_rank, _stable_json(record)


def _location_preference(record: dict[str, Any]) -> tuple[int, int, str]:
    precision = record.get("locationPrecision")
    precision_rank = _PRECISION_RANK.get(precision, -1) if record.get("coordinates") else -1
    return (
        precision_rank,
        SOURCE_RANK.get(record.get("sourceType"), 0),
        _stable_json(record),
    )


def _selected_record(records: list[dict[str, Any]], field: str) -> dict[str, Any] | None:
    candidates = [record for record in records if _present(record.get(field))]
    return max(candidates, key=lambda record: _field_preference(record, field)) if candidates else None


def _combine_external_ids(records: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    values: dict[str, set[str]] = {}
    for record in records:
        for namespace, external_id in (record.get("externalIds") or {}).items():
            values.setdefault(namespace, set()).add(external_id)
    selected: dict[str, str] = {}
    aliases: dict[str, list[str]] = {}
    for namespace, external_ids in sorted(values.items()):
        candidates = [
            record
            for record in records
            if (record.get("externalIds") or {}).get(namespace) in external_ids
        ]
        preferred = max(candidates, key=lambda record: _field_preference(record, "externalIds"))
        selected[namespace] = preferred["externalIds"][namespace]
        if len(external_ids) > 1:
            aliases[namespace] = sorted(external_ids)
    return selected, aliases


def _provenance(record: dict[str, Any], field: str) -> dict[str, Any]:
    return {
        "sourceType": record.get("sourceType"),
        "sourceIds": sorted(record.get("sourceIds") or []),
        "valueKind": _field_value_kind(record, field),
    }


def _record_anchor_id(namespace: str, identifier: str) -> str | None:
    slug = re.sub(r"[^a-z0-9]+", "-", identifier.casefold()).strip("-")[:64]
    return f"wattlas-record-{namespace}-{slug}" if slug else None


def _canonical_record_identity(
    records: list[dict[str, Any]],
) -> tuple[str, list[str], list[str]]:
    source_record_ids = sorted(
        {
            identifier
            for record in records
            for value in [record.get("id"), *(record.get("sourceRecordIds") or [])]
            if (identifier := canonical_identifier(value)) is not None
        }
    )
    anchors: set[tuple[int, str, str, str]] = set()
    for record in records:
        for namespace, identifier in _external_identity_map(record, entity=True).items():
            canonical_id = _record_anchor_id(namespace, identifier)
            if canonical_id is not None:
                anchors.add(
                    (
                        _RECORD_ANCHOR_PRIORITY.get(namespace, 15),
                        namespace,
                        identifier,
                        canonical_id,
                    )
                )
        relationship_field = "unitId" if _unit_record(record) else "plantId"
        relationship_id = canonical_identifier(record.get(relationship_field))
        if relationship_id is not None:
            namespace = "unitref" if relationship_field == "unitId" else "plantref"
            canonical_id = _record_anchor_id(namespace, relationship_id)
            if canonical_id is not None:
                anchors.add(
                    (
                        _RECORD_ANCHOR_PRIORITY[namespace],
                        namespace,
                        relationship_id,
                        canonical_id,
                    )
                )
    if anchors:
        ordered_anchors = sorted(anchors)
        primary_id = ordered_anchors[0][3]
        alternate_anchors = {anchor[3] for anchor in ordered_anchors[1:]}
    elif source_record_ids:
        primary_id = source_record_ids[0]
        alternate_anchors = set()
    else:
        raise ValueError("canonical power records require a durable anchor or source-row ID")
    existing_aliases = {
        normalized_alias
        for record in records
        for alias in record.get("idAliases", [])
        if (normalized_alias := canonical_identifier(alias)) is not None
    }
    aliases = sorted(
        (set(source_record_ids) | alternate_anchors | existing_aliases) - {primary_id}
    )
    return primary_id, aliases, source_record_ids


def _merge_record_cluster(records: list[dict[str, Any]]) -> dict[str, Any]:
    excluded = {
        "aliases",
        "evidence",
        "externalIdAliases",
        "externalIds",
        "fieldProvenance",
        "id",
        "idAliases",
        "sourceRecordIds",
        "sourceIds",
        *_FIELD_KIND_NAMES,
        *_COMPANION_KIND_FIELDS,
        *_LOCATION_FIELDS,
    }
    fields = sorted({field for record in records for field in record} - excluded)
    merged: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    for field in fields:
        selected = _selected_record(records, field)
        if selected is not None:
            merged[field] = deepcopy(selected[field])
            provenance[field] = _provenance(selected, field)

    for metric_field, kind_field in _FIELD_KIND_NAMES.items():
        selected = _selected_record(records, metric_field)
        if selected is None:
            continue
        merged[metric_field] = deepcopy(selected[metric_field])
        merged[kind_field] = selected.get(kind_field) or selected.get("valueKind")
        metric_provenance = _provenance(selected, metric_field)
        provenance[metric_field] = metric_provenance
        provenance[kind_field] = deepcopy(metric_provenance)

    location_record = max(records, key=_location_preference)
    for field in sorted(_LOCATION_FIELDS):
        if _present(location_record.get(field)):
            merged[field] = deepcopy(location_record[field])
            provenance[field] = _provenance(location_record, field)

    canonical_id, id_aliases, source_record_ids = _canonical_record_identity(records)
    merged["id"] = canonical_id
    merged["sourceRecordIds"] = source_record_ids
    if id_aliases:
        merged["idAliases"] = id_aliases

    merged["sourceIds"] = sorted(
        {source_id for record in records for source_id in record.get("sourceIds", [])}
    )
    external_ids, external_id_aliases = _combine_external_ids(records)
    merged["externalIds"] = external_ids
    if external_id_aliases:
        merged["externalIdAliases"] = external_id_aliases
    merged["aliases"] = sorted(
        {alias for record in records for alias in record.get("aliases", [])}
    )
    evidence_by_json = {
        _stable_json(claim): deepcopy(claim)
        for record in records
        for claim in record.get("evidence", [])
    }
    merged["evidence"] = sorted(
        evidence_by_json.values(),
        key=lambda claim: (
            str(claim.get("id", "")),
            str(claim.get("sourceId", "")),
            _stable_json(claim),
        ),
    )
    merged["fieldProvenance"] = dict(sorted(provenance.items()))

    all_secondary_fuels = {
        fuel
        for record in records
        for fuel in [record.get("secondaryFuel"), *(record.get("secondaryFuels") or [])]
        if fuel
    }
    primary_fuel = merged.get("primaryFuel")
    if primary_fuel:
        all_secondary_fuels.discard(primary_fuel)
    preferred_secondary_fuel = merged.get("secondaryFuel")
    merged["secondaryFuels"] = sorted(all_secondary_fuels)
    merged["secondaryFuel"] = (
        preferred_secondary_fuel
        if preferred_secondary_fuel in all_secondary_fuels
        else sorted(all_secondary_fuels)[0] if all_secondary_fuels else None
    )
    return merged


def _durable_record_identity(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "externalIds": record.get("externalIds") or {},
        "plantId": record.get("plantId"),
        "unitId": record.get("unitId"),
        "canonicalCountryKey": record.get("canonicalCountryKey"),
        "sourceRecordIds": sorted(record.get("sourceRecordIds") or []),
    }


def _unique_record_ids(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Disambiguate only genuine canonical-record ID collisions deterministically."""

    by_base: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_base.setdefault(record["id"], []).append(record)
    for base_id, collisions in by_base.items():
        if len(collisions) < 2:
            continue
        durable_identities = [_stable_json(_durable_record_identity(record)) for record in collisions]
        if len(set(durable_identities)) != len(durable_identities):
            raise ValueError(
                f"ambiguous duplicate canonical record ID {base_id!r} lacks distinct durable identity"
            )
        used: set[str] = set()
        ordered = sorted(
            collisions,
            key=lambda record: sha256(
                _stable_json(_durable_record_identity(record)).encode()
            ).hexdigest(),
        )
        for position, record in enumerate(ordered):
            digest = sha256(
                _stable_json(_durable_record_identity(record)).encode()
            ).hexdigest()[:10]
            candidate = f"{base_id}-{digest}"
            ordinal = 2
            while candidate in used:
                candidate = f"{base_id}-{digest}-{ordinal}"
                ordinal += 1
            used.add(candidate)
            if position == 0:
                record["idAliases"] = sorted(
                    set(record.get("idAliases", [])) | {base_id}
                )
            record["id"] = candidate
    return sorted(records, key=lambda record: (record["id"], _stable_json(record)))


def _sum_ranges(records: Iterable[dict[str, Any]]) -> dict[str, float] | None:
    capacities = [record["capacityMw"] for record in records if record.get("capacityMw")]
    if not capacities:
        return None
    return {
        part: sum(float(capacity[part]) for capacity in capacities)
        for part in ("low", "central", "high")
    }


def _capacity_by_technology(records: Iterable[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for record in records:
        capacity = record.get("capacityMw")
        if capacity:
            technology = record.get("technology") or "other"
            totals[technology] = totals.get(technology, 0.0) + float(capacity["central"])
    return dict(sorted(totals.items()))


def _capacity_field_lineage(record: dict[str, Any]) -> dict[str, Any]:
    field_provenance = (record.get("fieldProvenance") or {}).get("capacityMw")
    if isinstance(field_provenance, dict):
        return {
            "valueKind": field_provenance.get("valueKind")
            or record.get("capacityValueKind")
            or record.get("valueKind")
            or "unavailable",
            "sourceType": field_provenance.get("sourceType") or record.get("sourceType"),
            "sourceIds": sorted(field_provenance.get("sourceIds") or []),
        }
    return {
        "valueKind": record.get("capacityValueKind")
        or record.get("valueKind")
        or "unavailable",
        "sourceType": record.get("sourceType"),
        "sourceIds": sorted(record.get("sourceIds") or []),
    }


def _capacity_candidate_provenance(records: list[dict[str, Any]]) -> dict[str, Any]:
    lineages = [_capacity_field_lineage(record) for record in records]
    ranked_kinds = [lineage["valueKind"] for lineage in lineages]
    weakest_kind = min(
        ranked_kinds,
        key=lambda kind: (_VALUE_KIND_RANK.get(str(kind), 0), str(kind)),
    )
    selected_source_ids = {
        source_id for lineage in lineages for source_id in lineage["sourceIds"]
    }
    return {
        "valueKind": weakest_kind,
        "sourceTypes": sorted({str(lineage["sourceType"]) for lineage in lineages}),
        "sourceIds": sorted(selected_source_ids),
        "recordIds": sorted(record["id"] for record in records),
        "evidenceCount": sum(
            1
            for record in records
            for claim in record.get("evidence", [])
            if claim.get("sourceId") in selected_source_ids
        ),
    }


def _capacity_candidate_preference(records: list[dict[str, Any]]) -> tuple[int, int, int]:
    provenance = _capacity_candidate_provenance(records)
    return (
        _VALUE_KIND_RANK.get(str(provenance["valueKind"]), 0),
        min(SOURCE_RANK.get(source_type, 0) for source_type in provenance["sourceTypes"]),
        int(provenance["evidenceCount"]),
    )


def _capacity_account(
    records: list[dict[str, Any]],
    lifecycles: set[str],
) -> tuple[dict[str, float] | None, dict[str, float], dict[str, Any]]:
    units = [
        record
        for record in records
        if _unit_record(record) and record.get("lifecycle") in lifecycles
    ]
    aggregates = [
        record
        for record in records
        if not _unit_record(record)
        and record.get("lifecycle") in lifecycles
        and record.get("capacityMw") is not None
    ]
    known_units = [record for record in units if record.get("capacityMw") is not None]
    metadata: dict[str, Any] = {
        "knownUnitCount": len(known_units),
        "totalUnitCount": len(units),
    }
    complete_units = bool(units and len(known_units) == len(units))
    selected_aggregate = _selected_record(aggregates, "capacityMw") if aggregates else None
    if complete_units and selected_aggregate is not None:
        if _capacity_candidate_preference([selected_aggregate]) > _capacity_candidate_preference(
            known_units
        ):
            metadata.update(
                {
                    "method": "aggregate_preferred",
                    "coveragePercent": 100.0,
                    "provenance": _capacity_candidate_provenance([selected_aggregate]),
                    "completeUnitSumMw": _sum_ranges(known_units),
                }
            )
            return (
                deepcopy(selected_aggregate["capacityMw"]),
                _capacity_by_technology([selected_aggregate]),
                metadata,
            )
    if complete_units:
        metadata.update(
            {
                "method": "complete_unit_sum",
                "coveragePercent": 100.0,
                "provenance": _capacity_candidate_provenance(known_units),
            }
        )
        return _sum_ranges(known_units), _capacity_by_technology(known_units), metadata
    if units and aggregates:
        assert selected_aggregate is not None
        metadata["method"] = "aggregate_fallback"
        metadata["coveragePercent"] = round(len(known_units) / len(units) * 100, 2)
        metadata["partialKnownCapacityMw"] = _sum_ranges(known_units)
        metadata["provenance"] = _capacity_candidate_provenance([selected_aggregate])
        return (
            deepcopy(selected_aggregate["capacityMw"]),
            _capacity_by_technology([selected_aggregate]),
            metadata,
        )
    if units:
        metadata["method"] = "incomplete_units"
        metadata["coveragePercent"] = round(len(known_units) / len(units) * 100, 2)
        metadata["partialKnownCapacityMw"] = _sum_ranges(known_units)
        return None, {}, metadata
    if aggregates:
        assert selected_aggregate is not None
        metadata.update(
            {
                "method": "plant_aggregate",
                "coveragePercent": 100.0,
                "provenance": _capacity_candidate_provenance([selected_aggregate]),
            }
        )
        return (
            deepcopy(selected_aggregate["capacityMw"]),
            _capacity_by_technology([selected_aggregate]),
            metadata,
        )
    metadata.update({"method": "unavailable", "coveragePercent": 0.0})
    return None, {}, metadata


def _anchor_id(namespace: str, identifier: str) -> str | None:
    slug = re.sub(r"[^a-z0-9]+", "-", identifier.casefold()).strip("-")[:48]
    return f"wattlas-plant-{namespace}-{slug}" if slug else None


def _summary_anchors(records: list[dict[str, Any]]) -> list[tuple[int, str, str, str]]:
    identities: set[tuple[int, str, str, str]] = set()
    priority = {
        "wikidata": 0,
        "gemplant": 1,
        "wri": 2,
        "osm": 3,
        "official": 4,
        "wikipedia": 5,
    }
    for record in records:
        for namespace, identifier in _plant_identity_map(record).items():
            if namespace.startswith("plantref_") or namespace not in priority:
                continue
            generated_id = _anchor_id(namespace, identifier)
            if generated_id is not None:
                identities.add((priority[namespace], namespace, identifier, generated_id))
    return sorted(identities)


def _durable_plant_fingerprint(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "country": sorted({_country_key(record) for record in records}),
        "identities": sorted(
            (namespace, identifier)
            for record in records
            for namespace, identifier in _plant_identity_map(record).items()
        ),
        "coordinates": sorted(
            tuple(round(float(value), 4) for value in record["coordinates"])
            for record in records
            if record.get("coordinates")
        ),
        "recordIds": sorted(record["id"] for record in records),
    }


def _summary_anchor(records: list[dict[str, Any]]) -> tuple[str, str, list[str]]:
    anchors = _summary_anchors(records)
    if anchors:
        _, namespace, identifier, primary_id = anchors[0]
        aliases = sorted({anchor[3] for anchor in anchors if anchor[3] != primary_id})
        return primary_id, f"{namespace}:{identifier}", aliases
    fingerprint = {
        "country": sorted({_country_key(record) for record in records}),
        "names": sorted({_key(record.get("plantName") or record.get("name")) for record in records}),
        "coordinates": sorted(
            tuple(round(float(value), 4) for value in record["coordinates"])
            for record in records
            if record.get("coordinates")
        ),
        "recordIds": sorted(record["id"] for record in records),
    }
    digest = sha256(_stable_json(fingerprint).encode()).hexdigest()[:16]
    return f"wattlas-plant-derived-{digest}", _stable_json(fingerprint), []


def _summarize_plant(records: list[dict[str, Any]]) -> dict[str, Any]:
    units = [record for record in records if _unit_record(record)]
    counting_records = units if units else records
    name_record = _selected_record(records, "plantName") or _selected_record(records, "name")
    assert name_record is not None
    lifecycle_counts: dict[str, int] = {}
    for record in counting_records:
        lifecycle = record.get("lifecycle") or "unknown"
        lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + 1
    external_ids, external_id_aliases = _combine_external_ids(records)
    operating_capacity, operating_mix, operating_coverage = _capacity_account(
        records, _OPERATING_LIFECYCLES
    )
    planned_capacity, planned_mix, planned_coverage = _capacity_account(
        records, _PLANNED_LIFECYCLES
    )
    summary_id, anchor, id_aliases = _summary_anchor(records)
    location_record = max(records, key=_location_preference)
    summary = {
        "id": summary_id,
        "canonicalAnchor": anchor,
        "name": name_record.get("plantName") or name_record["name"],
        "country": location_record.get("country"),
        "canonicalCountryKey": location_record.get("canonicalCountryKey"),
        "geographyId": location_record.get("geographyId"),
        "coordinates": deepcopy(location_record.get("coordinates")),
        "locationPrecision": location_record.get("locationPrecision"),
        "unitCount": len(units),
        "recordCount": len(records),
        "technologies": sorted(
            {record.get("technology") or "other" for record in counting_records}
        ),
        "lifecycleCounts": dict(sorted(lifecycle_counts.items())),
        "operatingCapacityMw": operating_capacity,
        "plannedCapacityMw": planned_capacity,
        "operatingCapacityMwByTechnology": operating_mix,
        "plannedCapacityMwByTechnology": planned_mix,
        "operatingCapacityCoverage": operating_coverage,
        "plannedCapacityCoverage": planned_coverage,
        "sourceIds": sorted(
            {source_id for record in records for source_id in record.get("sourceIds", [])}
        ),
        "externalIds": external_ids,
        "aliases": sorted(
            {alias for record in records for alias in record.get("aliases", [])}
        ),
        "recordIds": sorted(record["id"] for record in records),
        "unitIds": sorted(record["unitId"] for record in units),
        "_collisionFingerprint": sha256(
            _stable_json(_durable_plant_fingerprint(records)).encode()
        ).hexdigest(),
    }
    if id_aliases:
        summary["idAliases"] = id_aliases
    if external_id_aliases:
        summary["externalIdAliases"] = external_id_aliases
    return summary


def _unique_summary_ids(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_base: dict[str, list[dict[str, Any]]] = {}
    for summary in summaries:
        by_base.setdefault(summary["id"], []).append(summary)
    for base_id, collisions in by_base.items():
        if len(collisions) > 1:
            ordered = sorted(collisions, key=lambda item: item["_collisionFingerprint"])
            for position, summary in enumerate(ordered):
                if position == 0:
                    summary["idAliases"] = sorted(
                        set(summary.get("idAliases", [])) | {base_id}
                    )
                summary["id"] = f"{base_id}-{summary['_collisionFingerprint'][:10]}"
    ordered_summaries = sorted(summaries, key=lambda summary: summary["id"])
    claimed_identifiers = {summary["id"] for summary in ordered_summaries}
    for summary in ordered_summaries:
        unique_aliases: list[str] = []
        for alias in sorted(set(summary.get("idAliases", []))):
            if alias not in claimed_identifiers:
                claimed_identifiers.add(alias)
                unique_aliases.append(alias)
        if unique_aliases:
            summary["idAliases"] = unique_aliases
        else:
            summary.pop("idAliases", None)
        summary.pop("_collisionFingerprint", None)
    return ordered_summaries


def canonicalize_power_plants(
    records: list[dict[str, Any]],
    *,
    geographies: list[dict] | None = None,
    aliases: dict[str, str] | None = None,
    country_aliases: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Canonicalize power records with indexed identity and fuzzy blocking.

    Exact matching is approximately O(n) in source rows. Conservative fuzzy
    matching only compares records sharing country, entity kind, operator/name,
    nearby one-degree cells, and neighboring ten-percent capacity bands. Bulk
    geography assignment builds one Shapely STRtree for the whole batch.
    """

    alias_map = {_key(key): _key(value) for key, value in (aliases or {}).items()}
    resolved_countries = _build_country_aliases(records, geographies, country_aliases)
    geography_index = build_geography_index(geographies) if geographies else None
    normalized = [
        _normalize_record(record, resolved_countries, geography_index)
        for record in records
    ]
    normalized.sort(key=lambda record: (record["id"], _stable_json(record)))
    canonical_records = _unique_record_ids(
        [
            _merge_record_cluster(cluster)
            for cluster in _indexed_clusters(normalized, alias_map, plant_group=False)
        ]
    )
    plants = _unique_summary_ids(
        [
            _summarize_plant(cluster)
            for cluster in _indexed_clusters(canonical_records, alias_map, plant_group=True)
        ]
    )
    units = sorted(
        [record for record in canonical_records if _unit_record(record)],
        key=lambda record: (str(record.get("unitId", "")), record["id"]),
    )
    return {"plants": plants, "units": units, "records": canonical_records}
