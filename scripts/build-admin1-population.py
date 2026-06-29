#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

import rasterio


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "src"))

from grid_scope.population import (  # noqa: E402
    TARGET_YEARS,
    apply_official_overrides,
    build_population_artifact,
    load_country_controls,
    load_csv_rows,
    reconcile_country_totals,
    write_population_artifact,
)


def _filename_source_year(source: Path) -> int | None:
    matches = {
        int(value)
        for value in re.findall(r"(?<!\d)((?:19|20|21)\d{2})(?!\d)", source.name)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _tagged_source_year(source: Path) -> int | None:
    with rasterio.open(source) as dataset:
        tags = {**dataset.tags(), **dataset.tags(1)}
    candidates: set[int] = set()
    for key, value in tags.items():
        if key.lower() not in {"source_year", "sourceyear", "year"}:
            continue
        if re.fullmatch(r"(?:19|20|21)\d{2}", str(value).strip()):
            candidates.add(int(value))
    if len(candidates) > 1:
        raise ValueError("WorldPop raster has ambiguous source-year tags")
    return next(iter(candidates)) if candidates else None


def _raster_configuration(
    source: Path,
    years: tuple[int, ...],
    explicit_source_year: int | None,
) -> tuple[dict[int, Path], dict[int, int], dict[str, object]]:
    if source.is_file():
        if explicit_source_year is not None:
            source_year = explicit_source_year
            method = "explicit_cli"
        else:
            filename_year = _filename_source_year(source)
            tagged_year = _tagged_source_year(source)
            candidates = {year for year in (filename_year, tagged_year) if year is not None}
            if len(candidates) > 1:
                raise ValueError("WorldPop filename and raster tags disagree on source year")
            if not candidates:
                raise ValueError(
                    "single WorldPop raster has no defensible source year; pass --source-year "
                    "or add a source_year raster tag"
                )
            source_year = next(iter(candidates))
            method = (
                "inferred_from_filename"
                if filename_year is not None
                else "inferred_from_raster_tags"
            )
        return (
            {year: source for year in years},
            {year: source_year for year in years},
            {"method": method, "sourceYear": source_year},
        )
    if not source.is_dir():
        raise ValueError(f"WorldPop source does not exist: {source}")
    if explicit_source_year is not None:
        raise ValueError("--source-year can only be used with a single WorldPop raster")
    result: dict[int, Path] = {}
    for year in years:
        matches = sorted({*source.glob(f"*{year}*.tif"), *source.glob(f"*{year}*.tiff")})
        if len(matches) != 1:
            raise ValueError(f"expected exactly one WorldPop raster for {year}, found {len(matches)}")
        result[year] = matches[0]
    resolved_paths = [path.resolve() for path in result.values()]
    if len(set(resolved_paths)) != len(resolved_paths):
        raise ValueError("one WorldPop raster ambiguously matches multiple source years")
    return (
        result,
        {year: year for year in years},
        {"method": "matched_distinct_target_year_files"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate version-pinned WorldPop counts to Wattlas ADM1 regions.")
    parser.add_argument("--boundaries", type=Path, required=True)
    parser.add_argument("--worldpop", type=Path, required=True)
    parser.add_argument(
        "--source-year",
        type=int,
        help="Actual source year of a single --worldpop raster; inferred from its filename when omitted.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release", default="worldpop-global2-configured")
    parser.add_argument("--source-id", default="worldpop-global2")
    parser.add_argument("--year", type=int, action="append", dest="years")
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--controls", type=Path)
    parser.add_argument("--reconciliation-tolerance", type=float, default=0.01)
    args = parser.parse_args()

    years = tuple(sorted(set(args.years or TARGET_YEARS)))
    if args.source_year is not None and not 1900 <= args.source_year <= 2100:
        parser.error("--source-year must be a defensible four-digit year")
    raster_paths, source_years, source_year_resolution = _raster_configuration(
        args.worldpop,
        years,
        args.source_year,
    )
    artifact = build_population_artifact(
        boundaries_path=args.boundaries,
        raster_paths=raster_paths,
        release_id=args.release,
        source_id=args.source_id,
        source_years_by_target=source_years,
        source_year_resolution=source_year_resolution,
    )
    if args.overrides:
        artifact = apply_official_overrides(artifact, load_csv_rows(args.overrides))
    if args.controls:
        artifact = reconcile_country_totals(
            artifact,
            load_country_controls(args.controls),
            tolerance=args.reconciliation_tolerance,
        )
    write_population_artifact(artifact, args.output)
    print(
        f"Wrote {len(artifact['records'])} ADM1 population records "
        f"({len(artifact['unavailable'])} unavailable) to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
