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
CARRY_FORWARD_METHOD_ID = "worldpop-carry-forward-v1"
CARRY_BACKWARD_METHOD_ID = "worldpop-carry-backward-v1"
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
    target_years: Iterable[int],
    source_years_by_target: Mapping[int, int],
    raster_paths_by_target: Mapping[int, Path],
    projection_methods_by_target: Mapping[int, str],
    source_year_resolution: Mapping[str, Any] | None,
) -> dict[str, Any]:
    targets = sorted(target_years)
    paths_by_source_year: dict[int, Path] = {}
    for target_year in targets:
        source_year = source_years_by_target[target_year]
        path = Path(raster_paths_by_target[target_year])
        existing = paths_by_source_year.get(source_year)
        if existing is not None and existing.resolve() != path.resolve():
            raise ValueError(f"source year {source_year} maps to multiple population rasters")
        paths_by_source_year[source_year] = path
    checksums_by_source_year = {
        year: checksum_file(path) for year, path in sorted(paths_by_source_year.items())
    }
    canonical = {
        "id": release_id,
        "sourceId": source_id,
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
                    "confidence": 70.0,
                    "coverage": round(coverage, 6),
                    "roundingMethod": ROUNDING_METHOD,
                    "adjustmentFactor": 1.0,
                })
                if year != source_year:
                    records[-1]["baseYear"] = source_year
    records.sort(key=lambda row: (row["geographyId"], row["year"]))
    unavailable.sort(key=lambda row: (row["geographyId"], row["year"]))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sourceRelease": _release_metadata(
            release_id=release_id,
            source_id=source_id,
            target_years=years,
            source_years_by_target=resolved_source_years,
            raster_paths_by_target=raster_paths,
            projection_methods_by_target=resolved_projection_methods,
            source_year_resolution=source_year_resolution,
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
    unavailable = result.get("unavailable")
    if not isinstance(unavailable, list):
        raise ValueError("population artifact requires unavailable records")
    by_key = {(row["geographyId"], int(row["year"])): index for index, row in enumerate(records)}
    unavailable_by_key = {
        (row["geographyId"], int(row["year"])): row for row in unavailable
    }
    changed = False
    for override in overrides:
        geography_id = str(override.get("geography_id") or "").strip()
        try:
            year = int(override.get("year", ""))
        except (TypeError, ValueError):
            raise ValueError("official population override requires a valid year") from None
        key = (geography_id, year)
        index = by_key.get(key)
        unavailable_match = unavailable_by_key.get(key)
        current = records[index] if index is not None else unavailable_match
        if current is None:
            continue
        country = str(override.get("country") or "").strip().upper()
        if unavailable_match is not None and country != current["country"]:
            continue
        if index is not None and country and country != current["country"]:
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
        replacement = {
            "geographyId": current["geographyId"],
            "name": current.get("name") or current["geographyId"],
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
        changed = True
    if changed:
        records.sort(key=lambda row: (row["geographyId"], row["year"]))
        unavailable.sort(key=lambda row: (row["geographyId"], row["year"]))
        result["unavailable"] = unavailable
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
    target_source_years: Mapping[int, int] | None = None,
    projection_methods_by_target: Mapping[int, str] | None = None,
) -> bool:
    if not path.exists():
        return True
    try:
        release = load_population_artifact(path)["sourceRelease"]
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
    return False
