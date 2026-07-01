from __future__ import annotations

import json
import math
import os
import re
import shutil
from hashlib import sha256
from pathlib import Path
from pathlib import PurePosixPath

from grid_scope.generator_artifacts import (
    generator_longitude_centroid,
    generator_point_bbox,
)
from grid_scope.snapshot_builder import expand_regional_energy

SNAPSHOT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SnapshotPublisher:
    def __init__(self, publish_dir: Path) -> None:
        self.publish_dir = publish_dir
        self._assert_no_symlink_ancestors(self.publish_dir)
        self.snapshots_dir = publish_dir / "snapshots"
        if self.snapshots_dir.is_symlink():
            raise ValueError("snapshots directory cannot be a symlink")
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def publish(
        self,
        snapshot_id: str,
        artifacts: dict[str, bytes],
        manifest: dict[str, object],
    ) -> Path:
        if not isinstance(snapshot_id, str) or not SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id):
            raise ValueError("snapshot ID must be a safe bounded slug")
        if manifest.get("snapshotId") != snapshot_id:
            raise ValueError("manifest snapshotId must match physical snapshot ID")
        self._validate(artifacts, manifest)

        temporary = self.snapshots_dir / f"{snapshot_id}.tmp"
        destination = self.snapshots_dir / snapshot_id
        latest_temp = self.publish_dir / "latest.json.tmp"
        latest_path = self.publish_dir / "latest.json"
        for path in (self.publish_dir, self.snapshots_dir, temporary, destination, latest_temp, latest_path):
            self._assert_no_symlink_ancestors(path)
        for path in (temporary, destination, latest_temp, latest_path):
            if path.is_symlink():
                raise ValueError(f"publisher control path cannot be a symlink: {path.name}")
        if latest_path.exists() and not latest_path.is_file():
            raise ValueError("latest.json must be a regular file")
        if destination.exists():
            raise ValueError(f"snapshot {snapshot_id} is immutable and already exists")
        if temporary.exists():
            self._remove_path(temporary)
        if latest_temp.exists():
            self._remove_path(latest_temp)
        temporary.mkdir(parents=True)
        committed = False
        try:
            checksums: dict[str, str] = {}
            for filename, body in artifacts.items():
                target = temporary / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
                checksums[filename] = sha256(body).hexdigest()
            complete_manifest = {**manifest, "checksums": checksums}
            (temporary / "manifest.json").write_text(
                json.dumps(complete_manifest, indent=2, sort_keys=True) + "\n"
            )
            os.replace(temporary, destination)
            committed = True
            latest_temp.write_text(json.dumps(complete_manifest, indent=2) + "\n")
            os.replace(latest_temp, latest_path)
            return destination
        except BaseException as publish_error:
            cleanup_errors: list[BaseException] = []
            cleanup_paths = []
            if committed:
                cleanup_paths.append(destination)
            else:
                cleanup_paths.append(temporary)
            cleanup_paths.append(latest_temp)
            for path in cleanup_paths:
                try:
                    self._remove_path(path)
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if cleanup_errors:
                details = "; ".join(str(error) for error in cleanup_errors)
                raise BaseExceptionGroup(
                    f"snapshot publish failed; cleanup failures: {details}",
                    [publish_error, *cleanup_errors],
                )
            raise

    @staticmethod
    def _assert_no_symlink_ancestors(path: Path) -> None:
        absolute = path.absolute()
        for component in reversed((absolute, *absolute.parents)):
            if component.is_symlink():
                raise ValueError(f"symlink ancestor is not allowed: {component}")

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_symlink():
            raise ValueError(f"publisher refuses to remove symlink: {path.name}")
        if not path.exists():
            return
        if path.is_file():
            path.unlink()
            return
        if path.is_dir():
            SnapshotPublisher._safe_rmtree(path)
            return
        raise ValueError(f"publisher refuses to remove special path: {path}")

    @staticmethod
    def _safe_rmtree(path: Path) -> None:
        if path.is_symlink():
            raise ValueError(f"publisher refuses to remove symlink: {path.name}")
        for child in path.rglob("*"):
            if child.is_symlink():
                raise ValueError(f"publisher refuses to follow symlink: {child}")
        shutil.rmtree(path)

    @staticmethod
    def _validate(artifacts: dict[str, bytes], manifest: dict[str, object]) -> None:
        for filename, body in artifacts.items():
            path = PurePosixPath(filename)
            if (
                not filename
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in filename
                or str(path) != filename
                or filename == "manifest.json"
                or not isinstance(body, bytes)
            ):
                raise ValueError(f"unsafe artifact path: {filename}")
        required = {
            "countries.geojson", "admin1.geojson", "regions.geojson", "assets.geojson",
            "regional-energy.json", "generator-overview.geojson", "generators/index.json",
            "evidence.json",
        }
        missing = required - artifacts.keys()
        if missing:
            raise ValueError(f"missing required artifacts: {', '.join(sorted(missing))}")
        for filename in (
            "countries.geojson", "admin1.geojson", "regions.geojson", "assets.geojson",
            "generator-overview.geojson",
        ):
            collection = json.loads(artifacts[filename])
            if collection.get("type") != "FeatureCollection":
                raise ValueError(f"{filename} must be a FeatureCollection")
            identifiers = [feature.get("id") for feature in collection.get("features", [])]
            present = [identifier for identifier in identifiers if identifier is not None]
            if len(present) != len(set(present)):
                raise ValueError(f"duplicate feature id in {filename}")
            if filename in {"countries.geojson", "admin1.geojson", "regions.geojson"}:
                semantic = [
                    (feature.get("properties") or {}).get("id") or feature.get("id")
                    for feature in collection.get("features", [])
                ]
                if any(not identifier for identifier in semantic) or len(semantic) != len(set(semantic)):
                    raise ValueError(f"duplicate semantic geography id in {filename}")
        countries = json.loads(artifacts["countries.geojson"])
        if not countries.get("features"):
            raise ValueError("countries.geojson must contain at least one country")
        country_ids = {
            feature.get("properties", {}).get("id") or feature.get("id")
            for feature in countries.get("features", [])
        }
        admin1 = json.loads(artifacts["admin1.geojson"])
        admin1_ids: set[str] = set()
        admin1_country: dict[str, str] = {}
        for feature in admin1.get("features", []):
            properties = feature.get("properties") or {}
            if properties.get("country") not in country_ids or properties.get("parentId") not in country_ids:
                raise ValueError(
                    f"admin1.geojson contains unknown parent country: {properties.get('parentId')}"
                )
            region_id = properties.get("id") or feature.get("id")
            admin1_ids.add(region_id)
            admin1_country[region_id] = properties.get("country")
            if "regionalEnergy" in properties or "generators" in properties:
                raise ValueError("admin1.geojson must not embed heavy regional or generator records")
        assets = json.loads(artifacts["assets.geojson"])
        for feature in assets.get("features", []):
            coordinates = (feature.get("geometry") or {}).get("coordinates")
            if (
                not isinstance(coordinates, list)
                or len(coordinates) != 2
                or any(isinstance(value, bool) for value in coordinates)
                or any(not isinstance(value, (int, float)) for value in coordinates)
                or not -180 <= coordinates[0] <= 180
                or not -90 <= coordinates[1] <= 90
            ):
                raise ValueError("assets.geojson contains invalid coordinates")
            country = (feature.get("properties") or {}).get("country")
            if country not in country_ids:
                raise ValueError(f"assets.geojson contains unknown country: {country}")
            if (feature.get("properties") or {}).get("category") == "power_generation":
                raise ValueError("power generators must be published only in country shards")

        regional_energy = expand_regional_energy(json.loads(artifacts["regional-energy.json"]))
        for geography_id, rows in regional_energy.items():
            if geography_id not in admin1_ids:
                raise ValueError(f"regional-energy.json contains unknown ADM1: {geography_id}")
            if not isinstance(rows, list) or [row.get("year") for row in rows] != list(range(2026, 2032)):
                raise ValueError(f"regional-energy.json has invalid time series for {geography_id}")

        overview = json.loads(artifacts["generator-overview.geojson"])
        overview_by_region: dict[str, dict[str, object]] = {}
        for feature in overview.get("features", []):
            properties = feature.get("properties") or {}
            geography_id = properties.get("geographyId")
            if geography_id not in admin1_ids:
                raise ValueError("generator overview contains unknown ADM1")
            if feature.get("id") != geography_id or geography_id in overview_by_region:
                raise ValueError("generator overview contains duplicate or mismatched ADM1 IDs")
            SnapshotPublisher._validate_point(feature, label="generator overview")
            SnapshotPublisher._nonnegative_number(
                properties.get("capacityMw"), label="generator overview capacity"
            )
            overview_by_region[geography_id] = feature

        index = json.loads(artifacts["generators/index.json"])
        entries = index.get("countries") if isinstance(index, dict) else None
        if not isinstance(entries, dict):
            raise ValueError("generator index countries must be an object")
        for country in entries:
            if country not in country_ids:
                raise ValueError(f"generator index contains unknown country: {country}")
        listed_paths = [
            entry.get("path")
            for entry in entries.values()
            if isinstance(entry, dict)
        ]
        actual_paths = {
            filename
            for filename in artifacts
            if filename.startswith("generators/") and filename.endswith(".geojson")
        }
        if len(listed_paths) != len(set(listed_paths)) or set(listed_paths) != actual_paths:
            raise ValueError("generator shard paths must exactly match generators/index.json")
        shard_ids: set[str] = set()
        indexed_count = 0
        indexed_country_capacities: list[float] = []
        regional_generators: dict[str, list[dict[str, object]]] = {}
        for country in sorted(entries):
            entry = entries[country]
            if country not in country_ids:
                raise ValueError(f"generator index contains unknown country: {country}")
            if not isinstance(entry, dict):
                raise ValueError(f"generator index entry for {country} must be an object")
            path = entry.get("path")
            expected_path = f"generators/{country}.geojson"
            if path != expected_path or expected_path not in artifacts:
                raise ValueError(f"generator index has invalid shard path for {country}")
            body = artifacts[expected_path]
            if entry.get("checksum") != sha256(body).hexdigest() or entry.get("bytes") != len(body):
                raise ValueError(f"generator index integrity mismatch for {country}")
            SnapshotPublisher._validate_bbox(entry.get("bbox"), country=country)
            shard = json.loads(body)
            if shard.get("type") != "FeatureCollection":
                raise ValueError(f"generator shard for {country} must be a FeatureCollection")
            features = shard.get("features", [])
            if entry.get("featureCount") != len(features):
                raise ValueError(f"generator index feature count mismatch for {country}")
            indexed_count += len(features)
            shard_rows: list[dict[str, object]] = []
            for feature in features:
                identifier = feature.get("id") or (feature.get("properties") or {}).get("id")
                if not identifier or identifier in shard_ids:
                    raise ValueError("duplicate generator id in country shards")
                shard_ids.add(identifier)
                properties = feature.get("properties") or {}
                if properties.get("country") != country:
                    raise ValueError(f"generator shard contains wrong country: {country}")
                if properties.get("geographyId") not in admin1_ids:
                    raise ValueError("generator shard contains unknown ADM1")
                if admin1_country[properties["geographyId"]] != country:
                    raise ValueError("generator shard ADM1 does not belong to its country")
                SnapshotPublisher._validate_point(feature, label="generator shard")
                operating_capacity = SnapshotPublisher._nonnegative_number(
                    properties.get("operatingCapacityMw", 0),
                    label="generator operating capacity",
                )
                planned_capacity = SnapshotPublisher._nonnegative_number(
                    properties.get("plannedCapacityMw", 0),
                    label="generator planned capacity",
                )
                expected_capacity = math.fsum((operating_capacity, planned_capacity))
                capacity = SnapshotPublisher._nonnegative_number(
                    properties.get("capacityMw", expected_capacity),
                    label="generator capacity",
                )
                if not math.isclose(
                    capacity, expected_capacity, rel_tol=0.0, abs_tol=1e-6
                ):
                    raise ValueError("generator capacity does not reconcile to lifecycle capacity")
                technology_mix = SnapshotPublisher._technology_mix(
                    properties.get("technologyMixMw"), capacity=capacity
                )
                coordinates = (feature.get("geometry") or {}).get("coordinates")
                shard_rows.append({
                    "id": identifier,
                    "country": country,
                    "geographyId": properties["geographyId"],
                    "coordinates": coordinates,
                    "capacityMw": capacity,
                    "operatingCapacityMw": operating_capacity,
                    "plannedCapacityMw": planned_capacity,
                    "technologyMixMw": technology_mix,
                })
            shard_rows.sort(key=lambda row: str(row["id"]))
            shard_capacity = math.fsum(float(row["capacityMw"]) for row in shard_rows)
            expected_bbox = generator_point_bbox(row["coordinates"] for row in shard_rows)
            if any(
                not math.isclose(
                    float(actual), float(expected), rel_tol=0.0, abs_tol=1e-9
                )
                for actual, expected in zip(entry["bbox"], expected_bbox, strict=True)
            ):
                raise ValueError(f"generator index bbox does not reconcile for {country}")
            for row in shard_rows:
                regional_generators.setdefault(str(row["geographyId"]), []).append(row)
            entry_capacity = SnapshotPublisher._nonnegative_number(
                entry.get("capacityMw", shard_capacity), label="generator index capacity"
            )
            if not math.isclose(
                entry_capacity, shard_capacity, rel_tol=0.0, abs_tol=1e-6
            ):
                raise ValueError(f"generator index capacity mismatch for {country}")
            indexed_country_capacities.append(shard_capacity)
        indexed_capacity = math.fsum(indexed_country_capacities)
        totals = index.get("totals") or {}
        if totals.get("featureCount") != indexed_count:
            raise ValueError("generator index total feature count does not reconcile")
        if not math.isclose(
            SnapshotPublisher._nonnegative_number(
                totals.get("capacityMw"), label="generator total capacity"
            ),
            indexed_capacity,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise ValueError("generator index total capacity does not reconcile")

        if set(overview_by_region) != set(regional_generators):
            raise ValueError("generator overview ADM1 set does not reconcile to indexed shards")
        for geography_id, rows in regional_generators.items():
            rows.sort(key=lambda row: str(row["id"]))
            expected_country = str(rows[0]["country"])
            operating = math.fsum(float(row["operatingCapacityMw"]) for row in rows)
            planned = math.fsum(float(row["plannedCapacityMw"]) for row in rows)
            capacity = math.fsum((operating, planned))
            technologies = sorted({
                technology
                for row in rows
                for technology in row["technologyMixMw"]
            })
            mix = {
                technology: math.fsum(
                    float(row["technologyMixMw"].get(technology, 0.0))
                    for row in rows
                )
                for technology in technologies
            }
            dominant = min(mix, key=lambda technology: (-mix[technology], technology))
            feature = overview_by_region[geography_id]
            properties = feature.get("properties") or {}
            overview_mix = SnapshotPublisher._technology_mix(
                properties.get("technologyMixMw"),
                capacity=SnapshotPublisher._nonnegative_number(
                    properties.get("capacityMw"), label="generator overview capacity"
                ),
            )
            expected_values = {
                "capacityMw": capacity,
                "operatingCapacityMw": operating,
                "plannedCapacityMw": planned,
            }
            if (
                properties.get("country") != expected_country
                or properties.get("count") != len(rows)
                or properties.get("dominantTechnology") != dominant
                or set(overview_mix) != set(mix)
                or any(
                    not math.isclose(
                        SnapshotPublisher._nonnegative_number(
                            properties.get(field), label=f"generator overview {field}"
                        ),
                        expected,
                        rel_tol=0.0,
                        abs_tol=1e-6,
                    )
                    for field, expected in expected_values.items()
                )
                or any(
                    not math.isclose(
                        SnapshotPublisher._nonnegative_number(
                            overview_mix.get(technology),
                            label="generator overview technology mix",
                        ),
                        expected,
                        rel_tol=0.0,
                        abs_tol=1e-6,
                    )
                    for technology, expected in mix.items()
                )
            ):
                raise ValueError(f"generator overview does not reconcile for ADM1 {geography_id}")
            coordinates = feature["geometry"]["coordinates"]
            expected_longitude = generator_longitude_centroid(
                float(row["coordinates"][0]) for row in rows
            )
            expected_latitude = math.fsum(float(row["coordinates"][1]) for row in rows) / len(rows)
            if not (
                math.isclose(
                    float(coordinates[0]), expected_longitude, rel_tol=0.0, abs_tol=1e-9
                )
                and math.isclose(
                    float(coordinates[1]), expected_latitude, rel_tol=0.0, abs_tol=1e-9
                )
            ):
                raise ValueError(f"generator overview centroid does not reconcile for ADM1 {geography_id}")

        guards = manifest.get("guards", {}) if isinstance(manifest, dict) else {}
        if not isinstance(guards, dict):
            raise ValueError("manifest guards must be an object")
        max_artifact_bytes = guards.get("maxArtifactBytes", 50_000_000)
        max_generator_features = guards.get("maxGeneratorFeatures", 2_000_000)
        if not isinstance(max_artifact_bytes, int) or max_artifact_bytes < 0:
            raise ValueError("artifact size guard must be a non-negative integer")
        if any(len(body) > max_artifact_bytes for body in artifacts.values()):
            raise ValueError("artifact size guard failed")
        if not isinstance(max_generator_features, int) or max_generator_features < 0:
            raise ValueError("generator feature-count guard must be a non-negative integer")
        if indexed_count > max_generator_features:
            raise ValueError("generator feature-count guard failed")
        connectors = manifest.get("connectors") if isinstance(manifest, dict) else None
        has_osm = any(
            connector.get("id") == "osm_infrastructure"
            and connector.get("state") in {"current", "cached"}
            for connector in (connectors or [])
            if isinstance(connector, dict)
        )
        coverage = manifest.get("coverage", {}) if isinstance(manifest, dict) else {}
        if has_osm and isinstance(coverage, dict) and coverage.get("dataCentres", 0) < 3_500:
            raise ValueError("OSM data-centre coverage guard failed")

    @staticmethod
    def _nonnegative_number(value: object, *, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be a finite non-negative number")
        parsed = float(value)
        if not math.isfinite(parsed) or parsed < 0:
            raise ValueError(f"{label} must be a finite non-negative number")
        return parsed

    @staticmethod
    def _validate_point(feature: dict[str, object], *, label: str) -> None:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if (
            not isinstance(coordinates, list)
            or len(coordinates) != 2
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in coordinates)
            or any(not math.isfinite(float(value)) for value in coordinates)
            or not -180 <= float(coordinates[0]) <= 180
            or not -90 <= float(coordinates[1]) <= 90
        ):
            raise ValueError(f"{label} contains invalid coordinates")

    @staticmethod
    def _validate_bbox(value: object, *, country: str) -> None:
        if (
            not isinstance(value, list)
            or len(value) != 4
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
            or any(not math.isfinite(float(item)) for item in value)
            or not -180 <= float(value[0]) <= 180
            or not -180 <= float(value[2]) <= 180
            or not -90 <= float(value[1]) <= float(value[3]) <= 90
        ):
            raise ValueError(f"generator index contains invalid bbox for {country}")

    @staticmethod
    def _technology_mix(value: object, *, capacity: float) -> dict[str, float]:
        if not isinstance(value, dict) or not value:
            raise ValueError("generator technology mix must be a nonempty object")
        mix = {
            str(technology): SnapshotPublisher._nonnegative_number(
                amount, label="generator technology capacity"
            )
            for technology, amount in value.items()
            if str(technology).strip()
        }
        if len(mix) != len(value) or not math.isclose(
            math.fsum(mix.values()), capacity, rel_tol=0.0, abs_tol=1e-6
        ):
            raise ValueError("generator technology mix does not reconcile to capacity")
        return mix
