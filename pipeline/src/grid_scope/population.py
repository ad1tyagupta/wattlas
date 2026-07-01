from __future__ import annotations

from copy import deepcopy
import csv
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.errors import WindowError
from rasterio.features import geometry_mask, geometry_window
from rasterio.warp import transform_geom
from rasterio.windows import Window
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from grid_scope.connectors.worldpop import WORLDPOP_SOURCE_ID, checksum_file


TARGET_YEARS = tuple(range(2026, 2032))
SCHEMA_VERSION = "wattlas-admin1-population-v1"
MODEL_METHOD_ID = "worldpop-zonal-sum-v1"
CARRY_FORWARD_METHOD_ID = "worldpop-carry-forward-v1"
CARRY_BACKWARD_METHOD_ID = "worldpop-carry-backward-v1"
ROUNDING_METHOD = "round-half-up"
DEFAULT_RECONCILIATION_TOLERANCE = 0.01


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _content_fingerprint(value: object) -> str:
    return f"sha256:{sha256(_stable_json(value).encode()).hexdigest()}"


def _method_versions() -> dict[str, str]:
    return {
        "schema": SCHEMA_VERSION,
        "zonalSum": MODEL_METHOD_ID,
        "carryForward": CARRY_FORWARD_METHOD_ID,
        "carryBackward": CARRY_BACKWARD_METHOD_ID,
        "rounding": ROUNDING_METHOD,
    }


def _seal_population_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    build_inputs = artifact.get("buildInputs")
    if not isinstance(build_inputs, dict):
        raise ValueError("population artifact requires build inputs before sealing")
    artifact["effectiveInputFingerprint"] = _content_fingerprint(build_inputs)
    payload = dict(artifact)
    payload.pop("buildFingerprint", None)
    artifact["buildFingerprint"] = _content_fingerprint(payload)
    return artifact


def _round_population(value: float | Decimal) -> int:
    rounded = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded)


def _strict_int(value: object, *, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value)
    raise ValueError(f"{label} must be an integer")


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
        if not identifier or re.fullmatch(r"[A-Z]{2}", country) is None:
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


def _polygon_components(geometry: Mapping[str, Any]) -> list[dict[str, Any]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon" and isinstance(coordinates, list):
        components = [{"type": "Polygon", "coordinates": coordinates}]
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        components = [
            {"type": "Polygon", "coordinates": component} for component in coordinates
        ]
    else:
        raise ValueError("population aggregation requires valid Polygon coordinates")
    polygons = [shape(component) for component in components]
    if any(polygon.is_empty or not polygon.is_valid for polygon in polygons):
        raise ValueError("ADM1 polygon geometry must be non-empty and valid")
    if len(polygons) == 1:
        return components

    # Public ADM1 releases sometimes encode adjacent island/sliver polygons as
    # separate MultiPolygon members that share an edge. Rasterizing those
    # members independently can select the same cell twice, so normalize their
    # topology before deriving the small per-component read windows.
    normalized = unary_union(polygons)
    if normalized.is_empty or not normalized.is_valid:
        raise ValueError("ADM1 MultiPolygon components could not be normalized safely")
    if normalized.geom_type == "Polygon":
        normalized_polygons = [normalized]
    elif normalized.geom_type == "MultiPolygon":
        normalized_polygons = list(normalized.geoms)
    else:
        raise ValueError("ADM1 MultiPolygon normalization produced non-polygon geometry")
    normalized_polygons.sort(key=lambda polygon: (*polygon.bounds, polygon.wkb_hex))
    return [dict(mapping(polygon)) for polygon in normalized_polygons]


def _reject_wraparound_rings(geometry: Mapping[str, Any]) -> None:
    for component in _polygon_components(geometry):
        coordinates = component["coordinates"]
        for ring in coordinates:
            longitudes = [float(position[0]) for position in ring]
            if longitudes and max(longitudes) - min(longitudes) > 180:
                raise ValueError(
                    "geographic polygon rings spanning more than 180 degrees must be "
                    "pre-split at the dateline"
                )


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
    total = 0.0
    selected_cells = 0
    valid_cells = 0
    for component in _polygon_components(geometry):
        window = _intersecting_window(dataset, component)
        if window is None or window.width <= 0 or window.height <= 0:
            return None
        for tile in _window_tiles(window, dataset.block_shapes[0]):
            # A band list keeps Rasterio on its 3-D read path, avoiding its deprecated
            # NumPy 2.5 single-band shape mutation while still reading one window.
            source_values = dataset.read([1], window=tile)[0]
            source_mask = dataset.read_masks([1], window=tile)[0]
            raw = source_values.astype(np.float64, copy=False)
            source_valid = source_mask > 0
            inside = geometry_mask(
                [component],
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


def _raster_coverage_reason(
    dataset: rasterio.io.DatasetReader,
    geometry: Mapping[str, Any],
) -> str | None:
    components = _polygon_components(geometry)
    # Global rasters can serialize an intended +180/-180 extent a tiny
    # fraction of a cell short (WorldPop's production raster is ~0.00017 of a
    # pixel short at +180). Treat sub-thousandth-pixel drift as numeric noise,
    # while retaining the fail-closed coverage check for real clipping.
    pixel_tolerance = max(
        abs(float(dataset.transform.a)),
        abs(float(dataset.transform.e)),
    ) * 1e-3
    raster_bounds = dataset.bounds
    any_intersection = False
    all_inside = True
    for component in components:
        left, bottom, right, top = shape(component).bounds
        intersects = not (
            right <= raster_bounds.left
            or left >= raster_bounds.right
            or top <= raster_bounds.bottom
            or bottom >= raster_bounds.top
        )
        any_intersection = any_intersection or intersects
        inside = (
            left >= raster_bounds.left - pixel_tolerance
            and right <= raster_bounds.right + pixel_tolerance
            and bottom >= raster_bounds.bottom - pixel_tolerance
            and top <= raster_bounds.top + pixel_tolerance
        )
        all_inside = all_inside and inside
    if all_inside:
        return None
    return "incomplete_raster_coverage" if any_intersection else "outside_raster_coverage"


def _release_metadata(
    *,
    release_id: str,
    source_id: str,
    target_years: Iterable[int],
    source_years_by_target: Mapping[int, int],
    raster_paths_by_target: Mapping[int, Path],
    projection_methods_by_target: Mapping[int, str],
    source_year_resolution: Mapping[str, Any] | None,
    source_url: str = "",
    licence: str = "",
    licence_url: str = "",
) -> dict[str, Any]:
    targets = sorted(target_years)
    paths_by_source_year: dict[int, Path] = {}
    source_year_by_path: dict[Path, int] = {}
    for target_year in targets:
        source_year = source_years_by_target[target_year]
        path = Path(raster_paths_by_target[target_year])
        resolved_path = path.resolve()
        existing = paths_by_source_year.get(source_year)
        if existing is not None and existing.resolve() != resolved_path:
            raise ValueError(f"source year {source_year} maps to multiple population rasters")
        existing_year = source_year_by_path.get(resolved_path)
        if existing_year is not None and existing_year != source_year:
            raise ValueError("one population raster cannot represent multiple source years")
        paths_by_source_year[source_year] = path
        source_year_by_path[resolved_path] = source_year
    checksums_by_source_year = {
        year: checksum_file(path) for year, path in sorted(paths_by_source_year.items())
    }
    canonical = {
        "id": release_id,
        "sourceId": source_id,
        "sourceUrl": source_url,
        "licence": licence,
        "licenceUrl": licence_url,
        "targetYears": targets,
        "sourceYears": sorted(paths_by_source_year),
        "targetSourceYears": {
            str(year): source_years_by_target[year] for year in targets
        },
        "projectionMethodsByTarget": {
            str(year): projection_methods_by_target[year] for year in targets
        },
        "checksumsSha256": {
            str(year): checksums_by_source_year[year]
            for year in sorted(checksums_by_source_year)
        },
        "rasterSources": [
            {
                "sourceYear": year,
                "fileName": paths_by_source_year[year].name,
                "checksumSha256": checksums_by_source_year[year],
                "sourceUrl": source_url,
                "licence": licence,
                "licenceUrl": licence_url,
            }
            for year in sorted(paths_by_source_year)
        ],
    }
    if source_year_resolution:
        canonical["sourceYearResolution"] = dict(source_year_resolution)
    fingerprint = sha256(_stable_json(canonical).encode()).hexdigest()
    return {**canonical, "fingerprint": f"sha256:{fingerprint}"}


def build_population_artifact(
    *,
    boundaries_path: Path,
    raster_paths: Mapping[int, Path],
    release_id: str,
    source_id: str = WORLDPOP_SOURCE_ID,
    source_years_by_target: Mapping[int, int] | None = None,
    projection_methods_by_target: Mapping[int, str] | None = None,
    source_year_resolution: Mapping[str, Any] | None = None,
    source_url: str = "",
    licence: str = "",
    licence_url: str = "",
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
    if (
        not source_url.startswith(("http://", "https://"))
        or licence != "CC-BY-4.0"
        or not licence_url.startswith(("http://", "https://"))
    ):
        raise ValueError("population source requires an official URL and CC-BY-4.0 licence")
    if source_years_by_target is None:
        resolved_source_years = {year: year for year in years}
    else:
        if set(source_years_by_target) != set(years):
            raise ValueError("population source-year mapping must cover every target year exactly")
        resolved_source_years = {year: int(source_years_by_target[year]) for year in years}
    if any(year < 1900 or year > 2100 for year in resolved_source_years.values()):
        raise ValueError("population source years must be defensible four-digit years")
    default_projection_methods = {
        year: (
            MODEL_METHOD_ID
            if year == resolved_source_years[year]
            else (
                CARRY_FORWARD_METHOD_ID
                if year > resolved_source_years[year]
                else CARRY_BACKWARD_METHOD_ID
            )
        )
        for year in years
    }
    if projection_methods_by_target is None:
        resolved_projection_methods = default_projection_methods
    else:
        if set(projection_methods_by_target) != set(years):
            raise ValueError("population projection methods must cover every target year exactly")
        resolved_projection_methods = {
            year: str(projection_methods_by_target[year]).strip() for year in years
        }
        if any(not method for method in resolved_projection_methods.values()):
            raise ValueError("population projection method IDs cannot be empty")
    for year in years:
        method_id = resolved_projection_methods[year]
        if year == resolved_source_years[year] and method_id != MODEL_METHOD_ID:
            raise ValueError("source-year targets must use the exact zonal-sum method")
        if year != resolved_source_years[year] and method_id == MODEL_METHOD_ID:
            raise ValueError("projected targets cannot claim the exact zonal-sum method")
    collection = json.loads(boundaries_path.read_text())
    if not isinstance(collection, Mapping):
        raise ValueError("boundary GeoJSON must be an object")
    boundary_crs = _boundary_crs(collection)
    features = _active_features(collection)
    if boundary_crs.is_geographic:
        for feature in features:
            _reject_wraparound_rings(feature["geometry"])
    records: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []

    for year in years:
        raster_path = Path(raster_paths[year])
        source_year = resolved_source_years[year]
        method_id = resolved_projection_methods[year]
        with rasterio.open(raster_path) as dataset:
            if dataset.count < 1:
                raise ValueError(f"WorldPop raster has no bands: {raster_path}")
            if dataset.crs is None:
                raise ValueError(f"WorldPop raster has no CRS: {raster_path}")
            for feature in features:
                geometry = feature["geometry"]
                if boundary_crs != dataset.crs:
                    geometry = transform_geom(boundary_crs, dataset.crs, geometry)
                coverage_reason = _raster_coverage_reason(dataset, geometry)
                if coverage_reason is not None:
                    unavailable.append({
                        "geographyId": feature["id"],
                        "name": feature["name"],
                        "country": feature["country"],
                        "year": year,
                        "reason": coverage_reason,
                    })
                    continue
                aggregated = _zonal_population(dataset, geometry)
                if aggregated is None:
                    unavailable.append({
                        "geographyId": feature["id"],
                        "name": feature["name"],
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
                    "sourceYear": source_year,
                    "sourceRelease": release_id,
                    "valueKind": "estimated",
                    "methodId": method_id,
                    "sourceIds": [source_id],
                    "sourceUrl": source_url,
                    "licence": licence,
                    "licenceUrl": licence_url,
                    "confidence": 70.0,
                    "coverage": round(coverage, 6),
                    "roundingMethod": ROUNDING_METHOD,
                    "adjustmentFactor": 1.0,
                })
                if year != source_year:
                    records[-1]["baseYear"] = source_year
    records.sort(key=lambda row: (row["geographyId"], row["year"]))
    unavailable.sort(key=lambda row: (row["geographyId"], row["year"]))
    source_release = _release_metadata(
        release_id=release_id,
        source_id=source_id,
        target_years=years,
        source_years_by_target=resolved_source_years,
        raster_paths_by_target=raster_paths,
        projection_methods_by_target=resolved_projection_methods,
        source_year_resolution=source_year_resolution,
        source_url=source_url,
        licence=licence,
        licence_url=licence_url,
    )
    artifact = {
        "schemaVersion": SCHEMA_VERSION,
        "sourceRelease": source_release,
        "roundingMethod": ROUNDING_METHOD,
        "buildInputs": {
            "boundaryChecksumSha256": checksum_file(boundaries_path),
            "methodVersions": _method_versions(),
            "targetSourceYears": source_release["targetSourceYears"],
            "projectionMethodsByTarget": source_release["projectionMethodsByTarget"],
            "rasterChecksumsSha256": source_release["checksumsSha256"],
            "officialOverridesFingerprint": _content_fingerprint([]),
            "countryControlsFingerprint": _content_fingerprint([]),
        },
        "records": records,
        "unavailable": unavailable,
    }
    sealed = _seal_population_artifact(artifact)
    _validate_population_artifact(sealed)
    return sealed


def apply_high_resolution_fallbacks(
    artifact: Mapping[str, Any],
    *,
    boundaries_path: Path,
    sources: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Fill only unavailable ADM1 rows from version-pinned country rasters.

    The primary global raster remains authoritative wherever it produced a
    value. Country 100m rasters are a narrow resolution fallback for polygons
    that contain no valid 1km cell, and every fallback is checksum-pinned in
    both release metadata and the effective build-input fingerprint.
    """

    result = deepcopy(dict(artifact))
    _validate_population_artifact(result)
    collection = json.loads(boundaries_path.read_text())
    if not isinstance(collection, Mapping):
        raise ValueError("boundary GeoJSON must be an object")
    boundary_crs = _boundary_crs(collection)
    features = {feature["id"]: feature for feature in _active_features(collection)}
    if checksum_file(boundaries_path) != result["buildInputs"]["boundaryChecksumSha256"]:
        raise ValueError("fallback boundaries do not match primary population artifact")

    normalized_sources: list[dict[str, Any]] = []
    source_paths: dict[str, Path] = {}
    countries: set[str] = set()
    for raw in sources:
        country = str(raw.get("country") or "").strip().upper()
        path = Path(raw.get("path") or "")
        checksum = str(raw.get("checksumSha256") or "").strip().lower()
        source_id = str(raw.get("sourceId") or "").strip()
        source_release = str(raw.get("sourceRelease") or "").strip()
        source_url = str(raw.get("sourceUrl") or "").strip()
        licence = str(raw.get("licence") or "").strip()
        licence_url = str(raw.get("licenceUrl") or "").strip()
        source_year = raw.get("sourceYear")
        arc_seconds = raw.get("resolutionArcSeconds")
        metres = raw.get("resolutionMetersAtEquator")
        if (
            re.fullmatch(r"[A-Z]{2}", country) is None
            or country in countries
            or isinstance(source_year, bool)
            or not isinstance(source_year, int)
            or not 1900 <= source_year <= 2100
            or not source_id
            or not source_release
            or not source_url.startswith(("http://", "https://"))
            or licence != "CC-BY-4.0"
            or not licence_url.startswith(("http://", "https://"))
            or isinstance(arc_seconds, bool)
            or not isinstance(arc_seconds, (int, float))
            or not math.isfinite(float(arc_seconds))
            or float(arc_seconds) <= 0
            or isinstance(metres, bool)
            or not isinstance(metres, (int, float))
            or not math.isfinite(float(metres))
            or float(metres) <= 0
            or not _valid_checksum(checksum)
        ):
            raise ValueError("invalid high-resolution population fallback source")
        if not path.is_file():
            raise ValueError(f"fallback population raster does not exist: {path}")
        if checksum_file(path) != checksum:
            raise ValueError(f"fallback raster checksum mismatch: {path.name}")
        countries.add(country)
        source_paths[country] = path
        normalized_sources.append({
            "country": country,
            "sourceYear": source_year,
            "fileName": path.name,
            "checksumSha256": checksum,
            "sourceId": source_id,
            "sourceRelease": source_release,
            "sourceUrl": source_url,
            "licence": licence,
            "licenceUrl": licence_url,
            "resolutionArcSeconds": float(arc_seconds),
            "resolutionMetersAtEquator": float(metres),
            "method": MODEL_METHOD_ID,
        })
    normalized_sources.sort(key=lambda row: row["country"])

    records = result["records"]
    unavailable = result["unavailable"]
    unavailable_by_country: dict[str, list[dict[str, Any]]] = {}
    for row in unavailable:
        unavailable_by_country.setdefault(row["country"], []).append(row)
    rescued_keys: set[tuple[str, int]] = set()
    for source in normalized_sources:
        candidates = unavailable_by_country.get(source["country"], [])
        if not candidates:
            continue
        source_year = source["sourceYear"]
        if any(
            result["sourceRelease"]["targetSourceYears"][str(row["year"])] != source_year
            for row in candidates
        ):
            raise ValueError("fallback source year disagrees with target/source mapping")
        with rasterio.open(source_paths[source["country"]]) as dataset:
            if dataset.count < 1 or dataset.crs is None:
                raise ValueError("fallback population raster requires one band and a CRS")
            aggregates: dict[str, tuple[float, float]] = {}
            for geography_id in sorted({row["geographyId"] for row in candidates}):
                feature = features.get(geography_id)
                if feature is None or feature["country"] != source["country"]:
                    raise ValueError("fallback geography is absent or has a country mismatch")
                geometry = feature["geometry"]
                if boundary_crs != dataset.crs:
                    geometry = transform_geom(boundary_crs, dataset.crs, geometry)
                if _raster_coverage_reason(dataset, geometry) is not None:
                    continue
                aggregate = _zonal_population(dataset, geometry)
                if aggregate is not None:
                    aggregates[geography_id] = aggregate
            for marker in candidates:
                aggregate = aggregates.get(marker["geographyId"])
                if aggregate is None:
                    continue
                population, coverage = aggregate
                year = marker["year"]
                method_id = result["sourceRelease"]["projectionMethodsByTarget"][str(year)]
                record = {
                    "geographyId": marker["geographyId"],
                    "name": marker["name"],
                    "country": marker["country"],
                    "year": year,
                    "population": _round_population(population),
                    "sourceYear": source_year,
                    "sourceRelease": source["sourceRelease"],
                    "valueKind": "estimated",
                    "methodId": method_id,
                    "sourceIds": [source["sourceId"]],
                    "sourceUrl": source["sourceUrl"],
                    "licence": source["licence"],
                    "licenceUrl": source["licenceUrl"],
                    "confidence": 70.0,
                    "coverage": round(coverage, 6),
                    "roundingMethod": ROUNDING_METHOD,
                    "adjustmentFactor": 1.0,
                    "fallbackSource": True,
                    "sourceResolutionArcSeconds": source["resolutionArcSeconds"],
                    "sourceResolutionMetersAtEquator": source["resolutionMetersAtEquator"],
                }
                if year != source_year:
                    record["baseYear"] = source_year
                records.append(record)
                rescued_keys.add((marker["geographyId"], year))

    result["records"] = sorted(records, key=lambda row: (row["geographyId"], row["year"]))
    result["unavailable"] = [
        row for row in unavailable if (row["geographyId"], row["year"]) not in rescued_keys
    ]
    result["sourceRelease"]["fallbackSources"] = normalized_sources
    release_payload = dict(result["sourceRelease"])
    release_payload.pop("fingerprint", None)
    result["sourceRelease"]["fingerprint"] = _content_fingerprint(release_payload)
    result["buildInputs"]["fallbackRasterSourcesFingerprint"] = _content_fingerprint(
        normalized_sources
    )
    sealed = _seal_population_artifact(result)
    _validate_population_artifact(sealed)
    return sealed


def apply_official_overrides(
    artifact: Mapping[str, Any],
    overrides: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    result = deepcopy(dict(artifact))
    _validate_population_artifact(result)
    records = result.get("records")
    if not isinstance(records, list):
        raise ValueError("population artifact requires records")
    unavailable = result.get("unavailable")
    if not isinstance(unavailable, list):
        raise ValueError("population artifact requires unavailable records")
    by_key = {(row["geographyId"], int(row["year"])): index for index, row in enumerate(records)}
    unavailable_by_key = {
        (row["geographyId"], int(row["year"])): row for row in unavailable
    }
    normalized_overrides: list[dict[str, Any]] = []
    override_keys: set[tuple[str, int]] = set()
    for override in overrides:
        geography_id = str(override.get("geography_id") or "").strip()
        if not geography_id:
            raise ValueError("official population override requires a geography ID")
        try:
            year = _strict_int(override.get("year"), label="official override year")
        except ValueError:
            raise ValueError("official population override requires a valid year") from None
        if year not in TARGET_YEARS:
            raise ValueError("official population override requires a valid year")
        key = (geography_id, year)
        if key in override_keys:
            raise ValueError(f"duplicate official population override: {geography_id} {year}")
        override_keys.add(key)
        country = str(override.get("country") or "").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", country) is None:
            raise ValueError("official population override requires an ISO2 country")
        try:
            population = _strict_int(
                override.get("population"),
                label="official override population",
            )
            confidence = float(override.get("confidence", 100))
            coverage = float(override.get("coverage", 100))
        except (TypeError, ValueError):
            raise ValueError("official population override has invalid numeric fields") from None
        source_id = str(override.get("source_id") or "").strip()
        source_url = str(override.get("source_url") or "").strip()
        release = str(override.get("release") or "").strip()
        method_id = str(override.get("method_id") or "official-adm1-population").strip()
        if (
            population < 0
            or not source_id
            or not source_url.startswith(("http://", "https://"))
            or not release
            or not method_id
        ):
            raise ValueError("official population override lacks valid population or public provenance")
        if (
            not math.isfinite(confidence)
            or not math.isfinite(coverage)
            or not 0 <= confidence <= 100
            or not 0 <= coverage <= 100
        ):
            raise ValueError("official override confidence and coverage must be within 0-100")
        normalized_overrides.append({
            "geographyId": geography_id,
            "country": country,
            "year": year,
            "population": population,
            "sourceId": source_id,
            "sourceUrl": source_url,
            "sourceRelease": release,
            "methodId": method_id,
            "confidence": confidence,
            "coverage": coverage,
        })

    rejections: list[dict[str, Any]] = []
    for override in sorted(
        normalized_overrides,
        key=lambda row: (row["geographyId"], row["year"]),
    ):
        geography_id = override["geographyId"]
        year = override["year"]
        key = (geography_id, year)
        index = by_key.get(key)
        unavailable_match = unavailable_by_key.get(key)
        current = records[index] if index is not None else unavailable_match
        if current is None:
            rejections.append({
                "geographyId": geography_id,
                "country": override["country"],
                "year": year,
                "reason": "unknown_geography_or_year",
            })
            continue
        if override["country"] != current["country"]:
            rejections.append({
                "geographyId": geography_id,
                "country": override["country"],
                "year": year,
                "reason": "country_mismatch",
                "expectedCountry": current["country"],
            })
            continue
        replacement = {
            "geographyId": current["geographyId"],
            "name": current.get("name") or current["geographyId"],
            "country": current["country"],
            "year": year,
            "population": override["population"],
            "sourceYear": year,
            "sourceRelease": override["sourceRelease"],
            "valueKind": "reported",
            "methodId": override["methodId"],
            "sourceIds": [override["sourceId"]],
            "sourceUrl": override["sourceUrl"],
            "confidence": override["confidence"],
            "coverage": override["coverage"],
            "roundingMethod": "official-reported-integer",
            "adjustmentFactor": 1.0,
        }
        if index is None:
            records.append(replacement)
            by_key[key] = len(records) - 1
            unavailable = [
                row
                for row in unavailable
                if (row["geographyId"], int(row["year"])) != key
            ]
            unavailable_by_key.pop(key, None)
        else:
            records[index] = replacement
    records.sort(key=lambda row: (row["geographyId"], row["year"]))
    unavailable.sort(key=lambda row: (row["geographyId"], row["year"]))
    rejections.sort(key=lambda row: (row["geographyId"], row["year"], row["reason"]))
    result["unavailable"] = unavailable
    result["overrideRejections"] = rejections
    build_inputs = result.get("buildInputs")
    if not isinstance(build_inputs, dict):
        raise ValueError("population artifact requires build inputs")
    build_inputs["officialOverridesFingerprint"] = _content_fingerprint(
        sorted(normalized_overrides, key=lambda row: (row["geographyId"], row["year"]))
    )
    sealed = _seal_population_artifact(result)
    _validate_population_artifact(sealed)
    return sealed


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
    _validate_population_artifact(result)
    records = result.get("records")
    if not isinstance(records, list):
        raise ValueError("population artifact requires records")
    normalized_controls: list[dict[str, Any]] = []
    for (raw_country, raw_year), control in sorted(controls.items()):
        country = str(raw_country).strip().upper()
        year = _strict_int(raw_year, label="country control year")
        if re.fullmatch(r"[A-Z]{2}", country) is None or year not in TARGET_YEARS:
            raise ValueError("country population control requires ISO2 country and target year")
        target = _strict_int(control.get("population"), label="country control population")
        source_id = str(control.get("sourceId") or control.get("source_id") or "").strip()
        if target < 0:
            raise ValueError("country population controls cannot be negative")
        if not source_id:
            raise ValueError("country population control requires a source ID")
        normalized_controls.append({
            "country": country,
            "year": year,
            "population": target,
            "sourceId": source_id,
        })
    for normalized in normalized_controls:
        country = normalized["country"]
        year = normalized["year"]
        rows = [row for row in records if row["country"] == country and int(row["year"]) == year]
        if not rows:
            continue
        target = normalized["population"]
        current = sum(int(row["population"]) for row in rows)
        source_id = normalized["sourceId"]
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
    build_inputs = result.get("buildInputs")
    if not isinstance(build_inputs, dict):
        raise ValueError("population artifact requires build inputs")
    build_inputs["countryControlsFingerprint"] = _content_fingerprint(normalized_controls)
    build_inputs["reconciliationTolerance"] = tolerance
    sealed = _seal_population_artifact(result)
    _validate_population_artifact(sealed)
    return sealed


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
        year = _strict_int(row.get("year"), label="country control year")
        key = (country, year)
        if key in controls:
            raise ValueError(f"duplicate country population control: {country} {year}")
        population = _strict_int(row.get("population"), label="country control population")
        source_id = str(row.get("sourceId") or row.get("source_id") or "").strip()
        if (
            re.fullmatch(r"[A-Z]{2}", country) is None
            or year not in TARGET_YEARS
            or population < 0
            or not source_id
        ):
            raise ValueError("country population control lacks valid values or provenance")
        controls[key] = {"population": population, "sourceId": source_id}
    return controls


def write_population_artifact(artifact: Mapping[str, Any], output: Path) -> None:
    _validate_population_artifact(dict(artifact))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_stable_json(artifact) + "\n", encoding="utf-8")


def _finite_quality(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"population {label} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0 <= numeric <= 100:
        raise ValueError(f"population {label} must be finite within 0-100")
    return numeric


def _valid_checksum(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _valid_fingerprint(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _valid_worldpop_provenance(value: Mapping[str, Any]) -> bool:
    return (
        str(value.get("sourceUrl") or "").startswith(("http://", "https://"))
        and value.get("licence") == "CC-BY-4.0"
        and str(value.get("licenceUrl") or "").startswith(("http://", "https://"))
    )


def _validate_source_release(release: object) -> dict[str, Any]:
    if not isinstance(release, dict):
        raise ValueError("population artifact requires source release metadata")
    if not str(release.get("id") or "").strip() or not str(release.get("sourceId") or "").strip():
        raise ValueError("population source release lacks identity")
    if not _valid_worldpop_provenance(release):
        raise ValueError("population source release lacks official URL or licence")
    fingerprint = release.get("fingerprint")
    canonical = dict(release)
    canonical.pop("fingerprint", None)
    if not _valid_fingerprint(fingerprint) or fingerprint != _content_fingerprint(canonical):
        raise ValueError("population source release fingerprint mismatch")
    target_years = release.get("targetYears")
    source_years = release.get("sourceYears")
    if (
        not isinstance(target_years, list)
        or not target_years
        or any(
            isinstance(year, bool) or not isinstance(year, int) or year not in TARGET_YEARS
            for year in target_years
        )
        or target_years != sorted(target_years)
        or len(target_years) != len(set(target_years))
    ):
        raise ValueError("population source release has invalid target years")
    if (
        not isinstance(source_years, list)
        or not source_years
        or any(
            isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2100
            for year in source_years
        )
        or source_years != sorted(source_years)
        or len(source_years) != len(set(source_years))
    ):
        raise ValueError("population source release has invalid source years")
    target_mapping = release.get("targetSourceYears")
    methods = release.get("projectionMethodsByTarget")
    checksums = release.get("checksumsSha256")
    if not isinstance(target_mapping, dict) or set(target_mapping) != {str(year) for year in target_years}:
        raise ValueError("population source release has invalid target/source mapping")
    if not isinstance(methods, dict) or set(methods) != set(target_mapping):
        raise ValueError("population source release has invalid projection mapping")
    if not isinstance(checksums, dict) or set(checksums) != {str(year) for year in source_years}:
        raise ValueError("population source release has invalid raster checksums")
    for target_year in target_years:
        source_year = target_mapping[str(target_year)]
        method_id = methods[str(target_year)]
        if source_year not in source_years or not isinstance(method_id, str) or not method_id.strip():
            raise ValueError("population source release has invalid target provenance")
        if target_year == source_year and method_id != MODEL_METHOD_ID:
            raise ValueError("exact population target has invalid method")
        if target_year != source_year and method_id == MODEL_METHOD_ID:
            raise ValueError("projected population target claims exact method")
    if any(not _valid_checksum(checksum) for checksum in checksums.values()):
        raise ValueError("population source release has invalid raster checksum")
    raster_sources = release.get("rasterSources")
    if not isinstance(raster_sources, list) or len(raster_sources) != len(source_years):
        raise ValueError("population source release has invalid raster sources")
    raster_years: set[int] = set()
    for raster_source in raster_sources:
        if not isinstance(raster_source, dict):
            raise ValueError("population source release has invalid raster source")
        source_year = raster_source.get("sourceYear")
        if (
            source_year not in source_years
            or source_year in raster_years
            or not str(raster_source.get("fileName") or "").strip()
            or raster_source.get("checksumSha256") != checksums[str(source_year)]
            or not _valid_worldpop_provenance(raster_source)
        ):
            raise ValueError("population source release has inconsistent raster source")
        raster_years.add(source_year)
    resolution = release.get("sourceYearResolution")
    if resolution is not None:
        if not isinstance(resolution, dict) or not str(resolution.get("method") or "").strip():
            raise ValueError("population source-year resolution is invalid")
        resolution_year = resolution.get("sourceYear")
        if resolution_year is not None and (
            isinstance(resolution_year, bool)
            or not isinstance(resolution_year, int)
            or not 1900 <= resolution_year <= 2100
        ):
            raise ValueError("population source-year resolution has invalid year")
    return release


def _validate_population_artifact(artifact: dict[str, Any]) -> None:
    if artifact.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported ADM1 population artifact schema")
    if artifact.get("roundingMethod") != ROUNDING_METHOD:
        raise ValueError("population artifact has unsupported rounding method")
    stored_seal = artifact.get("buildFingerprint")
    seal_payload = dict(artifact)
    seal_payload.pop("buildFingerprint", None)
    if not _valid_fingerprint(stored_seal) or stored_seal != _content_fingerprint(seal_payload):
        raise ValueError("population build fingerprint mismatch")
    build_inputs = artifact.get("buildInputs")
    if not isinstance(build_inputs, dict):
        raise ValueError("population artifact requires build inputs")
    if (
        not _valid_fingerprint(artifact.get("effectiveInputFingerprint"))
        or artifact.get("effectiveInputFingerprint") != _content_fingerprint(build_inputs)
    ):
        raise ValueError("population effective-input fingerprint mismatch")
    if not _valid_checksum(build_inputs.get("boundaryChecksumSha256")):
        raise ValueError("population build inputs require boundary checksum")
    if build_inputs.get("methodVersions") != _method_versions():
        raise ValueError("population artifact method versions are stale")
    for key in ("officialOverridesFingerprint", "countryControlsFingerprint"):
        value = build_inputs.get(key)
        if not _valid_fingerprint(value):
            raise ValueError(f"population build inputs require {key}")
    tolerance = build_inputs.get("reconciliationTolerance")
    if tolerance is not None and (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not math.isfinite(float(tolerance))
        or not 0 <= tolerance <= 1
    ):
        raise ValueError("population reconciliation tolerance is invalid")
    release = _validate_source_release(artifact.get("sourceRelease"))
    fallback_sources = release.get("fallbackSources", [])
    if not isinstance(fallback_sources, list):
        raise ValueError("population fallback sources must be an array")
    fallback_by_country: dict[str, dict[str, Any]] = {}
    for source in fallback_sources:
        if not isinstance(source, dict):
            raise ValueError("invalid population fallback source metadata")
        country = source.get("country")
        source_year = source.get("sourceYear")
        if (
            not isinstance(country, str)
            or re.fullmatch(r"[A-Z]{2}", country) is None
            or country in fallback_by_country
            or isinstance(source_year, bool)
            or not isinstance(source_year, int)
            or not 1900 <= source_year <= 2100
            or not str(source.get("fileName") or "").strip()
            or not _valid_checksum(source.get("checksumSha256"))
            or not str(source.get("sourceId") or "").strip()
            or not str(source.get("sourceRelease") or "").strip()
            or not str(source.get("sourceUrl") or "").startswith(("http://", "https://"))
            or not _valid_worldpop_provenance(source)
            or source.get("method") != MODEL_METHOD_ID
        ):
            raise ValueError("invalid population fallback source metadata")
        for field in ("resolutionArcSeconds", "resolutionMetersAtEquator"):
            value = source.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise ValueError("invalid population fallback resolution metadata")
        fallback_by_country[country] = source
    if fallback_sources != sorted(fallback_sources, key=lambda row: row["country"]):
        raise ValueError("population fallback sources must be sorted by country")
    fallback_fingerprint = build_inputs.get("fallbackRasterSourcesFingerprint")
    if fallback_sources:
        if fallback_fingerprint != _content_fingerprint(fallback_sources):
            raise ValueError("population fallback source fingerprint mismatch")
    elif fallback_fingerprint is not None:
        raise ValueError("population fallback fingerprint exists without sources")
    if build_inputs.get("targetSourceYears") != release["targetSourceYears"]:
        raise ValueError("population build target/source mapping mismatch")
    if build_inputs.get("projectionMethodsByTarget") != release["projectionMethodsByTarget"]:
        raise ValueError("population build projection mapping mismatch")
    if build_inputs.get("rasterChecksumsSha256") != release["checksumsSha256"]:
        raise ValueError("population build raster checksums mismatch")
    records = artifact.get("records")
    unavailable = artifact.get("unavailable")
    if not isinstance(records, list) or not isinstance(unavailable, list):
        raise ValueError("population artifact requires records and unavailable arrays")
    record_keys: set[tuple[str, int]] = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("population record must be an object")
        geography_id = str(row.get("geographyId") or "").strip()
        name = str(row.get("name") or "").strip()
        country = row.get("country")
        year = row.get("year")
        if not geography_id or not name:
            raise ValueError("population record requires geography and name")
        if not isinstance(country, str) or re.fullmatch(r"[A-Z]{2}", country) is None:
            raise ValueError("population record requires ISO2 country")
        if isinstance(year, bool) or not isinstance(year, int) or year not in release["targetYears"]:
            raise ValueError("population record has invalid year")
        key = (geography_id, year)
        if key in record_keys:
            raise ValueError("duplicate population geography/year record")
        record_keys.add(key)
        population = row.get("population")
        if isinstance(population, bool) or not isinstance(population, int) or population < 0:
            raise ValueError("population record population must be a nonnegative integer")
        source_year = row.get("sourceYear")
        if (
            isinstance(source_year, bool)
            or not isinstance(source_year, int)
            or not 1900 <= source_year <= 2100
        ):
            raise ValueError("population record has invalid source year")
        if not str(row.get("sourceRelease") or "").strip():
            raise ValueError("population record requires source release")
        method_id = str(row.get("methodId") or "").strip()
        source_ids = row.get("sourceIds")
        if (
            not method_id
            or not isinstance(source_ids, list)
            or not source_ids
            or any(not isinstance(item, str) or not item.strip() for item in source_ids)
        ):
            raise ValueError("population record lacks method or source IDs")
        _finite_quality(row.get("confidence"), label="confidence")
        _finite_quality(row.get("coverage"), label="coverage")
        adjustment = row.get("adjustmentFactor")
        if (
            isinstance(adjustment, bool)
            or not isinstance(adjustment, (int, float))
            or not math.isfinite(float(adjustment))
            or adjustment < 0
        ):
            raise ValueError("population adjustment factor must be finite and nonnegative")
        value_kind = row.get("valueKind")
        if value_kind not in {"estimated", "reported", "observed"}:
            raise ValueError("population record has invalid value kind")
        if value_kind == "estimated":
            if not _valid_worldpop_provenance(row):
                raise ValueError("estimated population record lacks WorldPop provenance")
            expected_source_year = release["targetSourceYears"][str(year)]
            if source_year != expected_source_year:
                raise ValueError("population record source year disagrees with release mapping")
            if method_id != release["projectionMethodsByTarget"][str(year)]:
                raise ValueError("population record method disagrees with release mapping")
            if source_year != year and row.get("baseYear") != source_year:
                raise ValueError("projected population record requires its base year")
        elif not str(row.get("sourceUrl") or "").startswith(("http://", "https://")):
            raise ValueError("reported population record requires a public source URL")
        if not str(row.get("roundingMethod") or "").strip():
            raise ValueError("population record requires a rounding method")
        if row.get("fallbackSource") is True:
            fallback = fallback_by_country.get(country)
            if (
                fallback is None
                or source_year != fallback["sourceYear"]
                or row.get("sourceRelease") != fallback["sourceRelease"]
                or source_ids != [fallback["sourceId"]]
                or row.get("sourceUrl") != fallback["sourceUrl"]
                or row.get("licence") != fallback["licence"]
                or row.get("licenceUrl") != fallback["licenceUrl"]
                or row.get("sourceResolutionArcSeconds") != fallback["resolutionArcSeconds"]
                or row.get("sourceResolutionMetersAtEquator")
                != fallback["resolutionMetersAtEquator"]
            ):
                raise ValueError("population fallback record disagrees with source metadata")
        elif "fallbackSource" in row:
            raise ValueError("population fallback marker must be true when present")
        if "countryControlPopulation" in row:
            control_population = row["countryControlPopulation"]
            if (
                isinstance(control_population, bool)
                or not isinstance(control_population, int)
                or control_population < 0
                or not str(row.get("controlSourceId") or "").strip()
            ):
                raise ValueError("population record has invalid country control provenance")
    unavailable_keys: set[tuple[str, int]] = set()
    for row in unavailable:
        if not isinstance(row, dict):
            raise ValueError("unavailable population marker must be an object")
        geography_id = str(row.get("geographyId") or "").strip()
        country = row.get("country")
        year = row.get("year")
        if (
            not geography_id
            or not str(row.get("name") or "").strip()
            or not isinstance(country, str)
            or re.fullmatch(r"[A-Z]{2}", country) is None
            or isinstance(year, bool)
            or not isinstance(year, int)
            or year not in release["targetYears"]
            or row.get("reason") not in {
                "outside_raster_coverage",
                "incomplete_raster_coverage",
            }
        ):
            raise ValueError("invalid unavailable population marker")
        key = (geography_id, year)
        if key in unavailable_keys:
            raise ValueError("duplicate unavailable population marker")
        if key in record_keys:
            raise ValueError("population record overlaps unavailable marker")
        unavailable_keys.add(key)
    rejections = artifact.get("overrideRejections", [])
    if not isinstance(rejections, list):
        raise ValueError("population override rejections must be an array")
    rejection_keys: set[tuple[str, int, str]] = set()
    for rejection in rejections:
        if not isinstance(rejection, dict):
            raise ValueError("population override rejection must be an object")
        geography_id = str(rejection.get("geographyId") or "").strip()
        country = rejection.get("country")
        year = rejection.get("year")
        reason = rejection.get("reason")
        if (
            not geography_id
            or not isinstance(country, str)
            or re.fullmatch(r"[A-Z]{2}", country) is None
            or isinstance(year, bool)
            or not isinstance(year, int)
            or year not in TARGET_YEARS
            or reason not in {"unknown_geography_or_year", "country_mismatch"}
        ):
            raise ValueError("invalid population override rejection")
        key = (geography_id, year, reason)
        if key in rejection_keys:
            raise ValueError("duplicate population override rejection")
        rejection_keys.add(key)
        if reason == "country_mismatch" and (
            not isinstance(rejection.get("expectedCountry"), str)
            or re.fullmatch(r"[A-Z]{2}", rejection["expectedCountry"]) is None
        ):
            raise ValueError("population country-mismatch rejection lacks expected country")


def load_population_artifact(path: Path) -> dict[str, Any]:
    artifact = json.loads(path.read_text())
    if not isinstance(artifact, dict):
        raise ValueError("invalid ADM1 population artifact")
    _validate_population_artifact(artifact)
    return artifact


def population_artifact_needs_rebuild(
    path: Path,
    *,
    release_id: str,
    checksums_by_year: Mapping[int, str],
    target_source_years: Mapping[int, int] | None = None,
    projection_methods_by_target: Mapping[int, str] | None = None,
    expected_effective_input_fingerprint: str | None = None,
    boundary_checksum_sha256: str | None = None,
    official_overrides_fingerprint: str | None = None,
    country_controls_fingerprint: str | None = None,
) -> bool:
    if not path.exists():
        return True
    try:
        artifact = load_population_artifact(path)
        release = artifact["sourceRelease"]
    except (OSError, ValueError, json.JSONDecodeError):
        return True
    expected = {str(year): checksum for year, checksum in sorted(checksums_by_year.items())}
    if release.get("id") != release_id or release.get("checksumsSha256") != expected:
        return True
    if target_source_years is not None:
        expected_mapping = {
            str(year): source_year for year, source_year in sorted(target_source_years.items())
        }
        if release.get("targetSourceYears") != expected_mapping:
            return True
    if projection_methods_by_target is not None:
        expected_methods = {
            str(year): method for year, method in sorted(projection_methods_by_target.items())
        }
        if release.get("projectionMethodsByTarget") != expected_methods:
            return True
    if (
        expected_effective_input_fingerprint is not None
        and artifact.get("effectiveInputFingerprint") != expected_effective_input_fingerprint
    ):
        return True
    build_inputs = artifact.get("buildInputs", {})
    if (
        boundary_checksum_sha256 is not None
        and build_inputs.get("boundaryChecksumSha256") != boundary_checksum_sha256
    ):
        return True
    if (
        official_overrides_fingerprint is not None
        and build_inputs.get("officialOverridesFingerprint") != official_overrides_fingerprint
    ):
        return True
    if (
        country_controls_fingerprint is not None
        and build_inputs.get("countryControlsFingerprint") != country_controls_fingerprint
    ):
        return True
    return False
