from __future__ import annotations

import json
import math
import os
import shutil
from hashlib import sha256
from pathlib import Path
from pathlib import PurePosixPath


class SnapshotPublisher:
    def __init__(self, publish_dir: Path) -> None:
        self.publish_dir = publish_dir
        self.snapshots_dir = publish_dir / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def publish(
        self,
        snapshot_id: str,
        artifacts: dict[str, bytes],
        manifest: dict[str, object],
    ) -> Path:
        self._validate(artifacts, manifest)

        temporary = self.snapshots_dir / f"{snapshot_id}.tmp"
        destination = self.snapshots_dir / snapshot_id
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)

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
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(temporary, destination)

        latest_temp = self.publish_dir / "latest.json.tmp"
        latest_temp.write_text(json.dumps(complete_manifest, indent=2) + "\n")
        os.replace(latest_temp, self.publish_dir / "latest.json")
        return destination

    @staticmethod
    def _validate(artifacts: dict[str, bytes], manifest: dict[str, object]) -> None:
        for filename, body in artifacts.items():
            path = PurePosixPath(filename)
            if (
                not filename
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in filename
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
        countries = json.loads(artifacts["countries.geojson"])
        if not countries.get("features"):
            raise ValueError("countries.geojson must contain at least one country")
        country_ids = {
            feature.get("properties", {}).get("id") or feature.get("id")
            for feature in countries.get("features", [])
        }
        admin1 = json.loads(artifacts["admin1.geojson"])
        admin1_ids: set[str] = set()
        for feature in admin1.get("features", []):
            properties = feature.get("properties") or {}
            if properties.get("country") not in country_ids or properties.get("parentId") not in country_ids:
                raise ValueError(
                    f"admin1.geojson contains unknown parent country: {properties.get('parentId')}"
                )
            region_id = properties.get("id") or feature.get("id")
            admin1_ids.add(region_id)
            if "regionalEnergy" in properties or "generators" in properties:
                raise ValueError("admin1.geojson must not embed heavy regional or generator records")
        assets = json.loads(artifacts["assets.geojson"])
        for feature in assets.get("features", []):
            coordinates = (feature.get("geometry") or {}).get("coordinates")
            if (
                not isinstance(coordinates, list)
                or len(coordinates) != 2
                or not -180 <= coordinates[0] <= 180
                or not -90 <= coordinates[1] <= 90
            ):
                raise ValueError("assets.geojson contains invalid coordinates")
            country = (feature.get("properties") or {}).get("country")
            if country not in country_ids:
                raise ValueError(f"assets.geojson contains unknown country: {country}")
            if (feature.get("properties") or {}).get("category") == "power_generation":
                raise ValueError("power generators must be published only in country shards")

        regional_energy = json.loads(artifacts["regional-energy.json"])
        if not isinstance(regional_energy, dict):
            raise ValueError("regional-energy.json must be keyed by geography ID")
        for geography_id, rows in regional_energy.items():
            if geography_id not in admin1_ids:
                raise ValueError(f"regional-energy.json contains unknown ADM1: {geography_id}")
            if not isinstance(rows, list) or [row.get("year") for row in rows] != list(range(2026, 2032)):
                raise ValueError(f"regional-energy.json has invalid time series for {geography_id}")

        overview = json.loads(artifacts["generator-overview.geojson"])
        for feature in overview.get("features", []):
            properties = feature.get("properties") or {}
            if properties.get("geographyId") not in admin1_ids:
                raise ValueError("generator overview contains unknown ADM1")
            SnapshotPublisher._validate_point(feature, label="generator overview")
            SnapshotPublisher._nonnegative_number(
                properties.get("capacityMw"), label="generator overview capacity"
            )

        index = json.loads(artifacts["generators/index.json"])
        entries = index.get("countries") if isinstance(index, dict) else None
        if not isinstance(entries, dict):
            raise ValueError("generator index countries must be an object")
        shard_ids: set[str] = set()
        indexed_count = 0
        indexed_capacity = 0.0
        for country, entry in entries.items():
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
            shard_capacity = 0.0
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
                SnapshotPublisher._validate_point(feature, label="generator shard")
                raw_capacity = properties.get("capacityMw")
                if raw_capacity is None:
                    raw_capacity = (
                        SnapshotPublisher._nonnegative_number(
                            properties.get("operatingCapacityMw", 0),
                            label="generator operating capacity",
                        )
                        + SnapshotPublisher._nonnegative_number(
                            properties.get("plannedCapacityMw", 0),
                            label="generator planned capacity",
                        )
                    )
                shard_capacity += SnapshotPublisher._nonnegative_number(
                    raw_capacity, label="generator capacity"
                )
            entry_capacity = SnapshotPublisher._nonnegative_number(
                entry.get("capacityMw", shard_capacity), label="generator index capacity"
            )
            if not math.isclose(entry_capacity, shard_capacity, abs_tol=1e-6):
                raise ValueError(f"generator index capacity mismatch for {country}")
            indexed_capacity += shard_capacity
        totals = index.get("totals") or {}
        if totals.get("featureCount") != indexed_count:
            raise ValueError("generator index total feature count does not reconcile")
        if not math.isclose(
            SnapshotPublisher._nonnegative_number(
                totals.get("capacityMw"), label="generator total capacity"
            ),
            indexed_capacity,
            abs_tol=1e-6,
        ):
            raise ValueError("generator index total capacity does not reconcile")

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
            or not -180 <= float(value[0]) <= float(value[2]) <= 180
            or not -90 <= float(value[1]) <= float(value[3]) <= 90
        ):
            raise ValueError(f"generator index contains invalid bbox for {country}")
