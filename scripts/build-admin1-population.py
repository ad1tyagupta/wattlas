#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys


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


def _raster_paths(source: Path, years: tuple[int, ...]) -> dict[int, Path]:
    if source.is_file():
        return {year: source for year in years}
    if not source.is_dir():
        raise ValueError(f"WorldPop source does not exist: {source}")
    result: dict[int, Path] = {}
    for year in years:
        matches = sorted({*source.glob(f"*{year}*.tif"), *source.glob(f"*{year}*.tiff")})
        if len(matches) != 1:
            raise ValueError(f"expected exactly one WorldPop raster for {year}, found {len(matches)}")
        result[year] = matches[0]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate version-pinned WorldPop counts to Wattlas ADM1 regions.")
    parser.add_argument("--boundaries", type=Path, required=True)
    parser.add_argument("--worldpop", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release", default="worldpop-global2-configured")
    parser.add_argument("--source-id", default="worldpop-global2")
    parser.add_argument("--year", type=int, action="append", dest="years")
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--controls", type=Path)
    parser.add_argument("--reconciliation-tolerance", type=float, default=0.01)
    args = parser.parse_args()

    years = tuple(sorted(set(args.years or TARGET_YEARS)))
    artifact = build_population_artifact(
        boundaries_path=args.boundaries,
        raster_paths=_raster_paths(args.worldpop, years),
        release_id=args.release,
        source_id=args.source_id,
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
