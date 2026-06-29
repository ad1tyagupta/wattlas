from __future__ import annotations

from copy import deepcopy
import csv
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.errors import WindowError
from rasterio.features import geometry_mask, geometry_window
from rasterio.warp import transform_geom
from rasterio.windows import Window

from grid_scope.connectors.worldpop import WORLDPOP_SOURCE_ID, checksum_file


TARGET_YEARS = tuple(range(2026, 2032))
SCHEMA_VERSION = "wattlas-admin1-population-v1"
MODEL_METHOD_ID = "worldpop-zonal-sum-v1"
ROUNDING_METHOD = "round-half-up"
DEFAULT_RECONCILIATION_TOLERANCE = 0.01


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _round_population(value: float | Decimal) -> int:
    rounded = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded)


def _boundary_crs(collection: Mapping[str, Any]) -> CRS:
    declared = collection.get("crs")
    if declared is None:
        # RFC 7946 GeoJSON coordinates are WGS84 longitude/latitude. Recording
        # that standard default is deliberate, rather than guessing from values.
        return CRS.from_epsg(4326)
    if not isinstance(declared, Mapping):
        raise ValueError("boundary GeoJSON CRS must be an object")
    properties = declared.get("properties")
    if not isinstance(properties, Mapping) or not properties.get("name"):
        raise ValueError("boundary GeoJSON CRS requires properties.name")
    try:
        return CRS.from_user_input(str(properties["name"]))
    except Exception as error:
        raise ValueError(f"invalid boundary CRS: {properties['name']}") from error


def _active_features(collection: Mapping[str, Any]) -> list[dict[str, Any]]:
    features = collection.get("features")
    if not isinstance(features, list):
        raise ValueError("boundary GeoJSON requires a features array")
    active: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for feature in features:
        if not isinstance(feature, Mapping):
            raise ValueError("boundary feature must be an object")
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, Mapping) or not isinstance(geometry, Mapping):
            raise ValueError("boundary feature requires properties and geometry")
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("population aggregation supports Polygon and MultiPolygon ADM1 geometry")
        identifier = str(properties.get("id") or feature.get("id") or "").strip()
        country = str(properties.get("country") or "").strip().upper()
        if not identifier or len(country) != 2:
            raise ValueError("boundary feature requires an ID and ISO2 country")
        if identifier in identifiers:
            raise ValueError(f"duplicate ADM1 boundary ID: {identifier}")
        identifiers.add(identifier)
        active.append({
            "id": identifier,
            "name": str(properties.get("name") or identifier),
            "country": country,
            "geometry": dict(geometry),
        })
    return active


def _intersecting_window(dataset: rasterio.io.DatasetReader, geometry: Mapping[str, Any]) -> Window | None:
    try:
        window = geometry_window(dataset, [geometry])
    except WindowError:
        return None
    full = Window(0, 0, dataset.width, dataset.height)
    try:
        return window.intersection(full).round_offsets().round_lengths()
    except WindowError:
        return None


def _window_tiles(window: Window, block_shape: tuple[int, int]) -> Iterable[Window]:
    block_height, block_width = block_shape
    row_start = int(window.row_off)
    col_start = int(window.col_off)
    row_stop = row_start + int(window.height)
    col_stop = col_start + int(window.width)
    for row in range(row_start, row_stop, block_height):
        for col in range(col_start, col_stop, block_width):
            yield Window(
                col,
                row,
                min(block_width, col_stop - col),
                min(block_height, row_stop - row),
            )


def _zonal_population(
    dataset: rasterio.io.DatasetReader,
    geometry: Mapping[str, Any],
) -> tuple[float, float] | None:
    window = _intersecting_window(dataset, geometry)
    if window is None or window.width <= 0 or window.height <= 0:
        return None
    total = 0.0
    selected_cells = 0
    valid_cells = 0
    for tile in _window_tiles(window, dataset.block_shapes[0]):
        # A band list keeps Rasterio on its 3-D read path, avoiding its deprecated
        # NumPy 2.5 single-band shape mutation while still reading one window.
        source_values = dataset.read([1], window=tile)[0]
        source_mask = dataset.read_masks([1], window=tile)[0]
        raw = source_values.astype(np.float64, copy=False)
        source_valid = source_mask > 0
        inside = geometry_mask(
            [geometry],
            out_shape=(int(tile.height), int(tile.width)),
            transform=dataset.window_transform(tile),
            invert=True,
            all_touched=False,
        )
        selected_cells += int(np.count_nonzero(inside))
        valid = inside & source_valid & np.isfinite(raw)
        if np.any(raw[valid] < 0):
            raise ValueError("WorldPop raster contains negative population outside nodata")
        valid_cells += int(np.count_nonzero(valid))
        total += float(raw[valid].sum(dtype=np.float64))
    if selected_cells == 0 or valid_cells == 0:
        return None
    coverage = valid_cells / selected_cells * 100
    return total, coverage


def _release_metadata(
    *,
    release_id: str,
    source_id: str,
    checksums_by_year: Mapping[int, str],
) -> dict[str, Any]:
    canonical = {
        "id": release_id,
        "sourceId": source_id,
        "checksumsSha256": {str(year): checksums_by_year[year] for year in sorted(checksums_by_year)},
        "supportedYears": sorted(checksums_by_year),
    }
    fingerprint = sha256(_stable_json(canonical).encode()).hexdigest()
    return {**canonical, "fingerprint": f"sha256:{fingerprint}"}


def build_population_artifact(
    *,
    boundaries_path: Path,
    raster_paths: Mapping[int, Path],
    release_id: str,
    source_id: str = WORLDPOP_SOURCE_ID,
) -> dict[str, Any]:
    """Aggregate version-pinned population count rasters to active ADM1 geometry.

    Raster cells are assigned by pixel centre (Rasterio/GDAL's default zonal
    convention), so Polygon holes and MultiPolygon components are respected.
    Source rasters are read in bounded windows and never loaded globally.
    """

    years = sorted(raster_paths)
    if not years or any(year not in TARGET_YEARS for year in years):
        raise ValueError("population raster years must be within 2026-2031")
    if not release_id.strip() or not source_id.strip():
        raise ValueError("population source release and source ID are required")
    collection = json.loads(boundaries_path.read_text())
    if not isinstance(collection, Mapping):
        raise ValueError("boundary GeoJSON must be an object")
    boundary_crs = _boundary_crs(collection)
    features = _active_features(collection)
    checksums = {year: checksum_file(Path(raster_paths[year])) for year in years}
    records: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []

    for year in years:
        raster_path = Path(raster_paths[year])
        with rasterio.open(raster_path) as dataset:
            if dataset.count < 1:
                raise ValueError(f"WorldPop raster has no bands: {raster_path}")
            if dataset.crs is None:
                raise ValueError(f"WorldPop raster has no CRS: {raster_path}")
            for feature in features:
                geometry = feature["geometry"]
                if boundary_crs != dataset.crs:
                    geometry = transform_geom(boundary_crs, dataset.crs, geometry)
                aggregated = _zonal_population(dataset, geometry)
                if aggregated is None:
                    unavailable.append({
                        "geographyId": feature["id"],
                        "country": feature["country"],
                        "year": year,
                        "reason": "outside_raster_coverage",
                    })
                    continue
                population, coverage = aggregated
                records.append({
                    "geographyId": feature["id"],
                    "name": feature["name"],
                    "country": feature["country"],
                    "year": year,
                    "population": _round_population(population),
                    "sourceYear": year,
                    "sourceRelease": release_id,
                    "valueKind": "estimated",
                    "methodId": MODEL_METHOD_ID,
                    "sourceIds": [source_id],
                    "confidence": 70.0,
                    "coverage": round(coverage, 6),
                    "roundingMethod": ROUNDING_METHOD,
                    "adjustmentFactor": 1.0,
                })
    records.sort(key=lambda row: (row["geographyId"], row["year"]))
    unavailable.sort(key=lambda row: (row["geographyId"], row["year"]))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sourceRelease": _release_metadata(
            release_id=release_id,
            source_id=source_id,
            checksums_by_year=checksums,
        ),
        "roundingMethod": ROUNDING_METHOD,
        "records": records,
        "unavailable": unavailable,
    }


def apply_official_overrides(
    artifact: Mapping[str, Any],
    overrides: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    result = deepcopy(dict(artifact))
    records = result.get("records")
    if not isinstance(records, list):
        raise ValueError("population artifact requires records")
    by_key = {(row["geographyId"], int(row["year"])): index for index, row in enumerate(records)}
    for override in overrides:
        geography_id = str(override.get("geography_id") or "").strip()
        try:
            year = int(override.get("year", ""))
        except (TypeError, ValueError):
            raise ValueError("official population override requires a valid year") from None
        index = by_key.get((geography_id, year))
        if index is None:
            continue
        current = records[index]
        country = str(override.get("country") or "").strip().upper()
        if country and country != current["country"]:
            continue
        try:
            population = int(override.get("population", ""))
            confidence = float(override.get("confidence", 100))
            coverage = float(override.get("coverage", 100))
        except (TypeError, ValueError):
            raise ValueError("official population override has invalid numeric fields") from None
        source_id = str(override.get("source_id") or "").strip()
        source_url = str(override.get("source_url") or "").strip()
        release = str(override.get("release") or "").strip()
        method_id = str(override.get("method_id") or "official-adm1-population").strip()
        if population < 0 or not source_id or not source_url or not release or not method_id:
            raise ValueError("official population override lacks valid population or public provenance")
        if not 0 <= confidence <= 100 or not 0 <= coverage <= 100:
            raise ValueError("official override confidence and coverage must be within 0-100")
        records[index] = {
            "geographyId": current["geographyId"],
            "name": current["name"],
            "country": current["country"],
            "year": year,
            "population": population,
            "sourceYear": year,
            "sourceRelease": release,
            "valueKind": "reported",
            "methodId": method_id,
            "sourceIds": [source_id],
            "sourceUrl": source_url,
            "confidence": confidence,
            "coverage": coverage,
            "roundingMethod": "official-reported-integer",
            "adjustmentFactor": 1.0,
        }
    return result


def _allocate_integer_total(rows: list[dict[str, Any]], total: int) -> list[int]:
    current_total = sum(int(row["population"]) for row in rows)
    if current_total <= 0:
        raise ValueError("cannot reconcile a positive country control without regional population shares")
    exact = [Decimal(int(row["population"])) * Decimal(total) / Decimal(current_total) for row in rows]
    allocated = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
    remainder = total - sum(allocated)
    order = sorted(
        range(len(rows)),
        key=lambda index: (-(exact[index] - allocated[index]), str(rows[index]["geographyId"])),
    )
    for index in order[:remainder]:
        allocated[index] += 1
    return allocated


def reconcile_country_totals(
    artifact: Mapping[str, Any],
    controls: Mapping[tuple[str, int], Mapping[str, Any]],
    *,
    tolerance: float = DEFAULT_RECONCILIATION_TOLERANCE,
) -> dict[str, Any]:
    if not 0 <= tolerance <= 1:
        raise ValueError("country reconciliation tolerance must be within 0-1")
    result = deepcopy(dict(artifact))
    records = result.get("records")
    if not isinstance(records, list):
        raise ValueError("population artifact requires records")
    for (country, year), control in sorted(controls.items()):
        rows = [row for row in records if row["country"] == country and int(row["year"]) == year]
        if not rows:
            continue
        target = int(control["population"])
        if target < 0:
            raise ValueError("country population controls cannot be negative")
        current = sum(int(row["population"]) for row in rows)
        source_id = str(control.get("sourceId") or control.get("source_id") or "").strip()
        if not source_id:
            raise ValueError("country population control requires a source ID")
        difference_ratio = abs(current - target) / max(target, 1)
        fixed = [row for row in rows if row.get("valueKind") in {"observed", "reported"}]
        modelled = [row for row in rows if row not in fixed]
        if difference_ratio <= tolerance:
            factor = 1.0
            allocations = [int(row["population"]) for row in modelled]
        else:
            fixed_total = sum(int(row["population"]) for row in fixed)
            residual = target - fixed_total
            if residual < 0:
                raise ValueError("official ADM1 population exceeds its country control")
            modelled_total = sum(int(row["population"]) for row in modelled)
            if not modelled and residual:
                raise ValueError("country control cannot be met without changing official ADM1 population")
            if modelled_total == 0:
                if residual:
                    raise ValueError("cannot reconcile country control from zero modelled regional shares")
                factor = 1.0
                allocations = [0 for _ in modelled]
            else:
                factor = residual / modelled_total
                allocations = _allocate_integer_total(modelled, residual)
        for row in fixed:
            row["adjustmentFactor"] = 1.0
            row["countryControlPopulation"] = target
            row["controlSourceId"] = source_id
        for row, population in zip(modelled, allocations, strict=True):
            row["population"] = population
            row["adjustmentFactor"] = round(factor, 12)
            row["countryControlPopulation"] = target
            row["controlSourceId"] = source_id
    records.sort(key=lambda row: (row["geographyId"], row["year"]))
    return result


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def load_country_controls(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text())
    else:
        rows = load_csv_rows(path)
    if not isinstance(rows, list):
        raise ValueError("country controls must be an array or CSV")
    controls: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        country = str(row.get("country") or "").strip().upper()
        year = int(row["year"])
        controls[(country, year)] = {
            "population": int(row["population"]),
            "sourceId": str(row.get("sourceId") or row.get("source_id") or "").strip(),
        }
    return controls


def write_population_artifact(artifact: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_stable_json(artifact) + "\n", encoding="utf-8")


def load_population_artifact(path: Path) -> dict[str, Any]:
    artifact = json.loads(path.read_text())
    if not isinstance(artifact, dict) or artifact.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported ADM1 population artifact schema")
    if not isinstance(artifact.get("records"), list) or not isinstance(artifact.get("sourceRelease"), dict):
        raise ValueError("invalid ADM1 population artifact")
    return artifact


def population_artifact_needs_rebuild(
    path: Path,
    *,
    release_id: str,
    checksums_by_year: Mapping[int, str],
) -> bool:
    if not path.exists():
        return True
    try:
        release = load_population_artifact(path)["sourceRelease"]
    except (OSError, ValueError, json.JSONDecodeError):
        return True
    expected = {str(year): checksum for year, checksum in sorted(checksums_by_year.items())}
    return release.get("id") != release_id or release.get("checksumsSha256") != expected
