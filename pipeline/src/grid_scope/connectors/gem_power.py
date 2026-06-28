from __future__ import annotations

import csv
from datetime import UTC, datetime
import io
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

import httpx

from grid_scope.config import GEM_GIPT_PATH, GEM_GIPT_URL
from grid_scope.connectors.base import ConnectorResult, FetchPayload
from grid_scope.models import ConnectorState


GEM_SOURCE_ID = "gem-global-integrated-power-tracker"
GEM_LICENCE = "CC-BY-4.0"
DEFAULT_MINIMUM_GEM_RECORDS = 10_000
_MAX_PLAUSIBLE_CAPACITY_MW = 100_000

_TECHNOLOGY_ALIASES = {
    "photovoltaic": "solar",
    "solar photovoltaic": "solar",
    "solar pv": "solar",
    "solar": "solar",
    "onshore wind": "wind",
    "offshore wind": "wind",
    "onshore_wind": "wind",
    "offshore_wind": "wind",
    "wind": "wind",
    "hydroelectric": "hydro",
    "hydropower": "hydro",
    "hydro": "hydro",
    "nuclear": "nuclear",
    "ccgt": "gas",
    "ocgt": "gas",
    "combined cycle": "gas",
    "gas": "gas",
    "natural gas": "gas",
    "coal": "coal",
    "oil": "oil",
    "petroleum": "oil",
    "biomass": "biomass",
    "bioenergy": "biomass",
    "geothermal": "geothermal",
}

_LIFECYCLE_ALIASES = {
    "operating": "operational",
    "operational": "operational",
    "construction": "under_construction",
    "under construction": "under_construction",
    "pre construction": "announced",
    "pre-construction": "announced",
    "planned": "announced",
    "announced": "announced",
    "retired": "retired",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "shelved": "shelved",
}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _row_value(row: dict[str, Any], *aliases: str) -> str | None:
    values = {_key(str(key)): value for key, value in row.items()}
    for alias in aliases:
        value = _clean(values.get(_key(alias)))
        if value is not None:
            return value
    return None


def _technology(*values: str | None) -> str:
    for value in values:
        normalized = _key(value or "")
        if normalized in _TECHNOLOGY_ALIASES:
            return _TECHNOLOGY_ALIASES[normalized]
        for alias, technology in _TECHNOLOGY_ALIASES.items():
            if alias in normalized:
                return technology
    return "other"


def _lifecycle(value: str | None) -> str:
    normalized = _key(value or "")
    lifecycle = _LIFECYCLE_ALIASES.get(normalized)
    if lifecycle is None:
        raise ValueError(f"unsupported GEM lifecycle: {value}")
    return lifecycle


def _number(value: str | None, *, label: str) -> float | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").strip()
    if not cleaned or cleaned.lower() in {"n/a", "na", "unknown", "not found", "-"}:
        return None
    try:
        number = float(cleaned)
    except ValueError as error:
        raise ValueError(f"invalid {label}: {value}") from error
    if not math.isfinite(number):
        raise ValueError(f"invalid {label}: {value}")
    return number


def _capacity(value: str | None) -> tuple[dict[str, float] | None, str]:
    capacity = _number(value, label="capacity")
    if capacity is None:
        return None, "unavailable"
    if capacity < 0 or capacity > _MAX_PLAUSIBLE_CAPACITY_MW:
        raise ValueError(f"impossible capacity: {capacity}")
    return {"low": capacity, "central": capacity, "high": capacity}, "reported"


def _coordinates(latitude: str | None, longitude: str | None) -> list[float] | None:
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


def _year(value: str | None, *, label: str) -> int | None:
    if value is None:
        return None
    match = re.search(r"\b(?:19|20)\d{2}\b", value)
    if not match:
        raise ValueError(f"invalid {label}: {value}")
    return int(match.group())


def _xlsx_rows(data: bytes) -> list[dict[str, str]]:
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(text.text or "" for text in item.findall(".//m:t", namespace))
                    for item in shared_root.findall("m:si", namespace)
                ]
            worksheet_names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            )
            if not worksheet_names:
                raise ValueError("GEM workbook has no worksheets")
            worksheet_root = ET.fromstring(archive.read(worksheet_names[0]))
    except (BadZipFile, ET.ParseError, KeyError) as error:
        raise ValueError("invalid GEM Excel workbook") from error

    table: list[list[str]] = []
    for row in worksheet_root.findall(".//m:sheetData/m:row", namespace):
        cells: dict[int, str] = {}
        for cell in row.findall("m:c", namespace):
            reference = cell.attrib.get("r", "A1")
            letters = re.match(r"[A-Z]+", reference)
            if letters is None:
                continue
            column = 0
            for character in letters.group():
                column = column * 26 + ord(character) - 64
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.findall(".//m:t", namespace))
            else:
                node = cell.find("m:v", namespace)
                value = node.text if node is not None and node.text is not None else ""
                if cell_type == "s" and value:
                    value = shared_strings[int(value)]
            cells[column - 1] = value
        width = max(cells, default=-1) + 1
        table.append([cells.get(index, "") for index in range(width)])
    if not table:
        return []
    headers = [header.strip() for header in table[0]]
    return [
        {header: values[index] if index < len(values) else "" for index, header in enumerate(headers)}
        for values in table[1:]
        if any(value.strip() for value in values)
    ]


def _read_rows(source: Path | str | bytes, *, suffix: str | None = None) -> list[dict[str, Any]]:
    if isinstance(source, bytes):
        data = source
        source_suffix = (suffix or ".csv").lower()
    else:
        path = Path(source)
        data = path.read_bytes()
        source_suffix = path.suffix.lower()
    if source_suffix in {".xlsx", ".xlsm"}:
        return _xlsx_rows(data)
    if source_suffix != ".csv":
        raise ValueError(f"unsupported GEM release format: {source_suffix}")
    text = data.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def parse_gem_power(source: Path | str | bytes, *, suffix: str | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, row in enumerate(_read_rows(source, suffix=suffix), start=2):
        plant_id = _row_value(row, "Plant ID", "GEM Plant ID", "Project ID")
        unit_id = _row_value(row, "Unit ID", "GEM Unit ID")
        name = _row_value(row, "Unit Name", "Project Name", "Plant Name")
        if not plant_id or not unit_id or not name:
            raise ValueError(f"GEM row {index} lacks plant ID, unit ID, or name")
        raw_status = _row_value(row, "Status", "Unit status")
        raw_technology = _row_value(row, "Technology", "Type")
        primary_fuel = _row_value(row, "Fuel 1", "Primary fuel", "Fuel")
        secondary_fuel = _row_value(row, "Fuel 2", "Secondary fuel")
        capacity, capacity_kind = _capacity(
            _row_value(row, "Capacity (MW)", "Capacity MW", "Unit capacity MW")
        )
        source_url = _row_value(row, "GEM Wiki URL", "Wiki URL", "URL")
        record = {
            "id": f"gem-unit-{unit_id}",
            "name": name,
            "plantName": _row_value(row, "Project Name", "Plant Name") or name,
            "category": "power_generation",
            "technology": _technology(raw_technology, primary_fuel),
            "primaryFuel": primary_fuel,
            "secondaryFuel": secondary_fuel,
            "lifecycle": _lifecycle(raw_status),
            "rawStatus": raw_status,
            "capacityMw": capacity,
            "capacityValueKind": capacity_kind,
            "plantId": f"gem-plant-{plant_id}",
            "unitId": f"gem-unit-{unit_id}",
            "externalIds": {"gemPlant": plant_id, "gemUnit": unit_id},
            "country": _row_value(row, "Country"),
            "subnationalUnit": _row_value(row, "Subnational unit", "State/Province"),
            "coordinates": _coordinates(
                _row_value(row, "Latitude"), _row_value(row, "Longitude")
            ),
            "owner": _row_value(row, "Owner", "Owner name"),
            "operator": _row_value(row, "Operator", "Operator name"),
            "commissioningYear": _year(
                _row_value(row, "Start year", "Commissioning year"), label="commissioning year"
            ),
            "retirementYear": _year(
                _row_value(row, "Retired year", "Retirement year"), label="retirement year"
            ),
            "expectedCommissioningYear": _year(
                _row_value(row, "Expected COD", "Expected commissioning year"),
                label="expected commissioning year",
            ),
            "sourceIds": [GEM_SOURCE_ID],
            "sourceType": "research_verified",
            "sourceUrl": source_url,
            "licence": GEM_LICENCE,
            "updatedAt": _row_value(row, "Last Updated", "Updated date"),
            "sourceRecord": {str(key): value for key, value in row.items()},
        }
        records.append(record)
    return records


class GemPowerConnector:
    source_id = "gem_power"

    def __init__(
        self,
        path: Path | str | None = GEM_GIPT_PATH,
        url: str | None = GEM_GIPT_URL,
        *,
        minimum_records: int = DEFAULT_MINIMUM_GEM_RECORDS,
    ) -> None:
        if minimum_records < 0:
            raise ValueError("minimum GEM record coverage cannot be negative")
        if url is not None:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("GEM release URL must be publicly addressable")
        self.path = Path(path) if path is not None else None
        self.url = url
        self.minimum_records = minimum_records

    def fetch(
        self,
        client: httpx.Client | None = None,
        *,
        now: datetime | None = None,
    ) -> ConnectorResult:
        checked_at = now or datetime.now(UTC)
        if self.path is None and self.url is None:
            return ConnectorResult(
                source_id=self.source_id,
                state=ConnectorState.NOT_CONFIGURED,
                payload=None,
                message="Set GEM_GIPT_PATH or GEM_GIPT_URL to a reusable public GEM GIPT release.",
            )
        if self.path is not None:
            release_bytes = self.path.read_bytes()
            suffix = self.path.suffix
            release_location = self.path.name
        else:
            if client is None:
                raise ValueError("an HTTP client is required for configured GEM_GIPT_URL")
            assert self.url is not None
            response = client.get(self.url)
            response.raise_for_status()
            release_bytes = response.content
            suffix = Path(urlparse(self.url).path).suffix or ".csv"
            release_location = self.url
        records = parse_gem_power(release_bytes, suffix=suffix)
        if len(records) < self.minimum_records:
            raise ValueError(
                f"too few GEM power records: {len(records)} < {self.minimum_records}"
            )
        body = json.dumps(
            {
                "source": GEM_SOURCE_ID,
                "sourceLocation": release_location,
                "licence": GEM_LICENCE,
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
