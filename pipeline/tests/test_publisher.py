import json
import os

import pytest

from grid_scope.generator_artifacts import build_generator_artifacts
from grid_scope.publisher import SnapshotPublisher


def global_artifacts() -> dict[str, bytes]:
    return {
        "countries.geojson": b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"AE","geometry":{"type":"Polygon","coordinates":[]},"properties":{"id":"AE"}}]}',
        "admin1.geojson": b'{"type":"FeatureCollection","features":[]}',
        "regions.geojson": b'{"type":"FeatureCollection","features":[]}',
        "assets.geojson": b'{"type":"FeatureCollection","features":[]}',
        "regional-energy.json": b'{}',
        "generator-overview.geojson": b'{"type":"FeatureCollection","features":[]}',
        "generators/index.json": b'{"countries":{},"totals":{"featureCount":0,"capacityMw":0}}',
        "evidence.json": b'{"sources":[],"claims":[]}',
    }


def test_failed_publish_keeps_last_known_good(tmp_path) -> None:
    publisher = SnapshotPublisher(tmp_path)
    publisher.publish(
        "first",
        global_artifacts(),
        {"snapshotId": "first"},
    )

    with pytest.raises(ValueError):
        publisher.publish("second", {}, {"snapshotId": "second"})

    latest = json.loads((tmp_path / "latest.json").read_text())
    assert latest["snapshotId"] == "first"


def test_publish_writes_checksummed_artifacts(tmp_path) -> None:
    publisher = SnapshotPublisher(tmp_path)
    publisher.publish(
        "first",
        global_artifacts(),
        {"snapshotId": "first"},
    )

    manifest = json.loads((tmp_path / "snapshots" / "first" / "manifest.json").read_text())
    assert len(manifest["checksums"]["countries.geojson"]) == 64


def test_publish_rejects_duplicate_asset_ids_and_keeps_last_good(tmp_path) -> None:
    publisher = SnapshotPublisher(tmp_path)
    publisher.publish("first", global_artifacts(), {"snapshotId": "first"})
    invalid = global_artifacts()
    invalid["assets.geojson"] = b'{"type":"FeatureCollection","features":[{"id":"same"},{"id":"same"}]}'

    with pytest.raises(ValueError, match="duplicate"):
        publisher.publish("second", invalid, {"snapshotId": "second"})

    assert json.loads((tmp_path / "latest.json").read_text())["snapshotId"] == "first"


def test_publish_rejects_invalid_asset_coordinates_and_unknown_country(tmp_path) -> None:
    publisher = SnapshotPublisher(tmp_path)
    invalid = global_artifacts()
    invalid["assets.geojson"] = json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "id": "bad",
            "geometry": {"type": "Point", "coordinates": [190, 95]},
            "properties": {"country": "ZZ"},
        }],
    }).encode()

    with pytest.raises(ValueError, match="invalid coordinates"):
        publisher.publish("invalid", invalid, {"snapshotId": "invalid"})


def test_publish_enforces_osm_coverage_guard_when_connector_is_present(tmp_path) -> None:
    publisher = SnapshotPublisher(tmp_path)
    manifest = {
        "snapshotId": "partial",
        "coverage": {"dataCentres": 14},
        "connectors": [{"id": "osm_infrastructure", "state": "current"}],
    }

    with pytest.raises(ValueError, match="coverage guard"):
        publisher.publish("partial", global_artifacts(), manifest)


def test_publish_rejects_invalid_admin1_parent_country(tmp_path) -> None:
    invalid = global_artifacts()
    invalid["admin1.geojson"] = b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"ZZ-1","geometry":{"type":"Polygon","coordinates":[]},"properties":{"id":"ZZ-1","country":"ZZ","parentId":"ZZ"}}]}'

    with pytest.raises(ValueError, match="unknown parent country"):
        SnapshotPublisher(tmp_path).publish("invalid", invalid, {"snapshotId": "invalid"})


def test_publish_writes_nested_generator_shards_and_manifest_checksums(tmp_path) -> None:
    artifacts = global_artifacts()
    shard = b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"plant-1","geometry":{"type":"Point","coordinates":[-119.5,36.5]},"properties":{"id":"plant-1","country":"US","geographyId":"US-CA","capacityMw":120,"operatingCapacityMw":120,"plannedCapacityMw":0,"technologyMixMw":{"solar":120},"technologies":["solar"]}}]}'
    artifacts["countries.geojson"] = b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"US","geometry":{"type":"Polygon","coordinates":[]},"properties":{"id":"US"}}]}'
    artifacts["admin1.geojson"] = b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"US-CA","geometry":{"type":"Polygon","coordinates":[]},"properties":{"id":"US-CA","country":"US","parentId":"US"}}]}'
    artifacts["generators/US.geojson"] = shard
    artifacts["generator-overview.geojson"] = b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"US-CA","geometry":{"type":"Point","coordinates":[-119.5,36.5]},"properties":{"geographyId":"US-CA","country":"US","count":1,"capacityMw":120,"operatingCapacityMw":120,"plannedCapacityMw":0,"technologyMixMw":{"solar":120},"dominantTechnology":"solar"}}]}'
    import hashlib
    artifacts["generators/index.json"] = json.dumps({
        "countries": {"US": {
            "bbox": [-119.5, 36.5, -119.5, 36.5], "path": "generators/US.geojson",
            "featureCount": 1, "checksum": hashlib.sha256(shard).hexdigest(), "bytes": len(shard),
        }},
        "totals": {"featureCount": 1, "capacityMw": 120},
    }, separators=(",", ":"), sort_keys=True).encode()

    destination = SnapshotPublisher(tmp_path).publish("with-shards", artifacts, {"snapshotId": "with-shards"})

    assert (destination / "generators" / "US.geojson").read_bytes() == shard
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest["checksums"]["generators/US.geojson"] == hashlib.sha256(shard).hexdigest()


def test_publish_rejects_unindexed_generator_shards(tmp_path) -> None:
    invalid = global_artifacts()
    invalid["generators/US.geojson"] = b'{"type":"FeatureCollection","features":[]}'

    with pytest.raises(ValueError, match="shard paths"):
        SnapshotPublisher(tmp_path).publish("invalid", invalid, {"snapshotId": "invalid"})


def test_publish_rejects_missing_and_duplicate_indexed_shard_paths(tmp_path) -> None:
    missing = global_artifacts()
    missing["generators/index.json"] = b'{"countries":{"AE":{"path":"generators/AE.geojson"}},"totals":{"featureCount":0,"capacityMw":0}}'
    with pytest.raises(ValueError, match="shard paths"):
        SnapshotPublisher(tmp_path).publish("missing", missing, {"snapshotId": "missing"})

    duplicate = global_artifacts()
    duplicate["countries.geojson"] = b'{"type":"FeatureCollection","features":[{"id":"AE","properties":{"id":"AE"}},{"id":"US","properties":{"id":"US"}}]}'
    duplicate["generators/AE.geojson"] = b'{"type":"FeatureCollection","features":[]}'
    duplicate["generators/index.json"] = b'{"countries":{"AE":{"path":"generators/AE.geojson"},"US":{"path":"generators/AE.geojson"}},"totals":{"featureCount":0,"capacityMw":0}}'
    with pytest.raises(ValueError, match="shard paths"):
        SnapshotPublisher(tmp_path).publish("duplicate", duplicate, {"snapshotId": "duplicate"})


def test_publish_rejects_overview_that_does_not_reconcile_to_shards(tmp_path) -> None:
    artifacts = global_artifacts()
    artifacts["countries.geojson"] = b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"US","geometry":{"type":"Polygon","coordinates":[]},"properties":{"id":"US"}}]}'
    artifacts["admin1.geojson"] = b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"US-CA","geometry":{"type":"Polygon","coordinates":[]},"properties":{"id":"US-CA","country":"US","parentId":"US"}}]}'
    shard = b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"plant-1","geometry":{"type":"Point","coordinates":[-119.5,36.5]},"properties":{"id":"plant-1","country":"US","geographyId":"US-CA","capacityMw":120,"operatingCapacityMw":120,"plannedCapacityMw":0,"technologyMixMw":{"solar":120}}}]}'
    import hashlib
    artifacts["generators/US.geojson"] = shard
    artifacts["generators/index.json"] = json.dumps({
        "countries": {"US": {
            "bbox": [-119.5, 36.5, -119.5, 36.5], "path": "generators/US.geojson",
            "featureCount": 1, "checksum": hashlib.sha256(shard).hexdigest(),
            "bytes": len(shard), "capacityMw": 120,
        }},
        "totals": {"featureCount": 1, "capacityMw": 120},
    }, separators=(",", ":"), sort_keys=True).encode()

    with pytest.raises(ValueError, match="overview.*ADM1"):
        SnapshotPublisher(tmp_path).publish("missing", artifacts, {"snapshotId": "missing"})

    artifacts["generator-overview.geojson"] = b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"US-CA","geometry":{"type":"Point","coordinates":[-119.5,36.5]},"properties":{"geographyId":"US-CA","country":"US","count":2,"capacityMw":999,"operatingCapacityMw":999,"plannedCapacityMw":0,"technologyMixMw":{"coal":999},"dominantTechnology":"coal"}}]}'
    with pytest.raises(ValueError, match="overview.*reconcile"):
        SnapshotPublisher(tmp_path).publish("fabricated", artifacts, {"snapshotId": "fabricated"})


def test_publish_rejects_generator_assigned_to_foreign_country_adm1(tmp_path) -> None:
    artifacts = global_artifacts()
    artifacts["countries.geojson"] = b'{"type":"FeatureCollection","features":[{"id":"AE","properties":{"id":"AE"}},{"id":"US","properties":{"id":"US"}}]}'
    artifacts["admin1.geojson"] = b'{"type":"FeatureCollection","features":[{"id":"US-CA","properties":{"id":"US-CA","country":"US","parentId":"US"}}]}'
    shard = b'{"type":"FeatureCollection","features":[{"id":"plant-1","geometry":{"type":"Point","coordinates":[-119.5,36.5]},"properties":{"id":"plant-1","country":"AE","geographyId":"US-CA","capacityMw":120,"operatingCapacityMw":120,"plannedCapacityMw":0,"technologyMixMw":{"solar":120}}}]}'
    import hashlib
    artifacts["generators/AE.geojson"] = shard
    artifacts["generators/index.json"] = json.dumps({
        "countries": {"AE": {
            "bbox": [-119.5, 36.5, -119.5, 36.5], "path": "generators/AE.geojson",
            "featureCount": 1, "checksum": hashlib.sha256(shard).hexdigest(),
            "bytes": len(shard), "capacityMw": 120,
        }},
        "totals": {"featureCount": 1, "capacityMw": 120},
    }, separators=(",", ":"), sort_keys=True).encode()
    artifacts["generator-overview.geojson"] = b'{"type":"FeatureCollection","features":[{"id":"US-CA","geometry":{"type":"Point","coordinates":[-119.5,36.5]},"properties":{"geographyId":"US-CA","country":"AE","count":1,"capacityMw":120,"operatingCapacityMw":120,"plannedCapacityMw":0,"technologyMixMw":{"solar":120},"dominantTechnology":"solar"}}]}'

    with pytest.raises(ValueError, match="ADM1.*country"):
        SnapshotPublisher(tmp_path).publish("invalid", artifacts, {"snapshotId": "invalid"})


def test_builder_output_with_adversarial_capacities_always_publishes(tmp_path) -> None:
    countries = {
        "type": "FeatureCollection",
        "features": [{"id": "US", "properties": {"id": "US"}}],
    }
    admin1 = {
        "type": "FeatureCollection",
        "features": [{
            "id": "US-CA",
            "properties": {"id": "US-CA", "country": "US", "parentId": "US"},
        }],
    }
    plants = [
        {
            "id": plant_id, "country": "US", "geographyId": "US-CA",
            "coordinates": [-120 + position, 36], "technologies": ["solar"],
            "operatingCapacityMw": capacity, "plannedCapacityMw": 0,
            "sourceIds": ["public-registry"],
        }
        for position, (plant_id, capacity) in enumerate((
            ("plant-a", 10_000_000_000_000_000.0),
            ("plant-b", 1.0),
            ("plant-c", 1.0),
        ))
    ]
    base = global_artifacts()
    base["countries.geojson"] = json.dumps(countries, separators=(",", ":")).encode()
    base["admin1.geojson"] = json.dumps(admin1, separators=(",", ":")).encode()

    for snapshot_id, rows in (("forward", plants), ("reverse", list(reversed(plants)))):
        artifacts = {**base, **build_generator_artifacts(countries, admin1, rows)}
        destination = SnapshotPublisher(tmp_path).publish(
            snapshot_id, artifacts, {"snapshotId": snapshot_id}
        )
        assert (destination / "generators" / "US.geojson").exists()


@pytest.mark.parametrize("snapshot_id", ["", ".", "..", "../escape", "a/b", "a\\b", "x" * 129])
def test_publish_rejects_unsafe_snapshot_ids(tmp_path, snapshot_id) -> None:
    with pytest.raises(ValueError, match="snapshot ID"):
        SnapshotPublisher(tmp_path).publish(snapshot_id, global_artifacts(), {"snapshotId": snapshot_id})
    assert not (tmp_path.parent / "escape").exists()


def test_publish_requires_manifest_id_to_match_physical_snapshot(tmp_path) -> None:
    with pytest.raises(ValueError, match="manifest snapshotId"):
        SnapshotPublisher(tmp_path).publish("physical", global_artifacts(), {"snapshotId": "other"})


def test_same_id_republish_and_latest_failure_preserve_last_good(tmp_path, monkeypatch) -> None:
    publisher = SnapshotPublisher(tmp_path)
    first = publisher.publish("first", global_artifacts(), {"snapshotId": "first"})
    original = (first / "evidence.json").read_bytes()
    changed = global_artifacts()
    changed["evidence.json"] = b'{"sources":[{"id":"changed"}],"claims":[]}'
    with pytest.raises(ValueError, match="immutable"):
        publisher.publish("first", changed, {"snapshotId": "first"})
    assert (first / "evidence.json").read_bytes() == original

    real_replace = os.replace
    def fail_latest(source, destination):
        if str(destination).endswith("latest.json"):
            raise OSError("simulated latest failure")
        return real_replace(source, destination)
    monkeypatch.setattr("grid_scope.publisher.os.replace", fail_latest)
    with pytest.raises(OSError, match="latest failure"):
        publisher.publish("second", global_artifacts(), {"snapshotId": "second"})
    assert json.loads((tmp_path / "latest.json").read_text())["snapshotId"] == "first"
    assert not (tmp_path / "snapshots" / "second").exists()


def test_publish_rejects_symlinked_control_paths(tmp_path) -> None:
    publisher = SnapshotPublisher(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (publisher.snapshots_dir / "evil.tmp").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        publisher.publish("evil", global_artifacts(), {"snapshotId": "evil"})
    assert outside.exists()
    (publisher.snapshots_dir / "evil.tmp").unlink()
    (publisher.snapshots_dir / "dest").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        publisher.publish("dest", global_artifacts(), {"snapshotId": "dest"})
    (publisher.snapshots_dir / "dest").unlink()
    (tmp_path / "latest.json.tmp").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        publisher.publish("latest-temp", global_artifacts(), {"snapshotId": "latest-temp"})

    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        SnapshotPublisher(linked_root)


def test_publish_rejects_symlinked_publish_ancestor(tmp_path) -> None:
    outside = tmp_path / "outside-ancestor"
    outside.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink.*ancestor"):
        SnapshotPublisher(linked_parent / "publish")


def test_stale_regular_snapshot_temp_is_safely_recovered(tmp_path) -> None:
    publisher = SnapshotPublisher(tmp_path)
    stale = publisher.snapshots_dir / "recover.tmp"
    stale.write_text("stale partial snapshot")

    destination = publisher.publish(
        "recover", global_artifacts(), {"snapshotId": "recover"}
    )

    assert destination.is_dir()
    assert not stale.exists()


def test_latest_temp_cleanup_failure_does_not_block_snapshot_rollback(
    tmp_path, monkeypatch
) -> None:
    publisher = SnapshotPublisher(tmp_path)
    publisher.publish("first", global_artifacts(), {"snapshotId": "first"})
    real_replace = os.replace

    def inject_stale_latest_directory(source, destination):
        result = real_replace(source, destination)
        if str(destination).endswith("snapshots/second"):
            (tmp_path / "latest.json.tmp").mkdir()
        return result

    real_remove = publisher._remove_path
    def fail_only_latest_cleanup(path):
        if path == tmp_path / "latest.json.tmp":
            raise OSError("simulated stale latest cleanup failure")
        return real_remove(path)

    monkeypatch.setattr("grid_scope.publisher.os.replace", inject_stale_latest_directory)
    monkeypatch.setattr(publisher, "_remove_path", fail_only_latest_cleanup)

    with pytest.raises(BaseException, match="stale latest cleanup failure"):
        publisher.publish("second", global_artifacts(), {"snapshotId": "second"})
    assert not (publisher.snapshots_dir / "second").exists()
    assert json.loads((tmp_path / "latest.json").read_text())["snapshotId"] == "first"


def test_publish_rejects_semantic_duplicate_ids_and_bool_coordinates(tmp_path) -> None:
    duplicate = global_artifacts()
    duplicate["countries.geojson"] = b'{"type":"FeatureCollection","features":[{"id":"AE-1","properties":{"id":"AE"}},{"id":"AE-2","properties":{"id":"AE"}}]}'
    with pytest.raises(ValueError, match="duplicate semantic"):
        SnapshotPublisher(tmp_path).publish("duplicate", duplicate, {"snapshotId": "duplicate"})

    invalid = global_artifacts()
    invalid["assets.geojson"] = b'{"type":"FeatureCollection","features":[{"id":"bad","geometry":{"type":"Point","coordinates":[true,25]},"properties":{"country":"AE"}}]}'
    with pytest.raises(ValueError, match="invalid coordinates"):
        SnapshotPublisher(tmp_path).publish("bool", invalid, {"snapshotId": "bool"})


def test_publish_reconciles_bbox_and_antimeridian_overview(tmp_path) -> None:
    countries = {"type": "FeatureCollection", "features": [{"id": "US", "properties": {"id": "US"}}]}
    admin1 = {"type": "FeatureCollection", "features": [{"id": "US-AK", "properties": {"id": "US-AK", "country": "US", "parentId": "US"}}]}
    plants = [
        {"id": "east", "country": "US", "geographyId": "US-AK", "coordinates": [179, 52], "technologies": ["wind"], "operatingCapacityMw": 1, "plannedCapacityMw": 0, "sourceIds": ["public"]},
        {"id": "west", "country": "US", "geographyId": "US-AK", "coordinates": [-179, 54], "technologies": ["wind"], "operatingCapacityMw": 1, "plannedCapacityMw": 0, "sourceIds": ["public"]},
    ]
    artifacts = global_artifacts()
    artifacts["countries.geojson"] = json.dumps(countries).encode()
    artifacts["admin1.geojson"] = json.dumps(admin1).encode()
    artifacts.update(build_generator_artifacts(countries, admin1, plants))
    index = json.loads(artifacts["generators/index.json"])
    assert index["countries"]["US"]["bbox"][0] > index["countries"]["US"]["bbox"][2]
    overview = json.loads(artifacts["generator-overview.geojson"])
    assert abs(abs(overview["features"][0]["geometry"]["coordinates"][0]) - 180) < 1e-9
    SnapshotPublisher(tmp_path).publish("dateline", artifacts, {"snapshotId": "dateline"})

    index["countries"]["US"]["bbox"] = [0, 0, 1, 1]
    artifacts["generators/index.json"] = json.dumps(index).encode()
    with pytest.raises(ValueError, match="bbox.*reconcile"):
        SnapshotPublisher(tmp_path).publish("bad-bbox", artifacts, {"snapshotId": "bad-bbox"})


def test_publish_rejects_bad_generator_index_and_keeps_last_good(tmp_path) -> None:
    publisher = SnapshotPublisher(tmp_path)
    publisher.publish("first", global_artifacts(), {"snapshotId": "first"})
    invalid = global_artifacts()
    invalid["generators/index.json"] = b'{"countries":{"ZZ":{"bbox":[0,0,0,0],"path":"generators/ZZ.geojson","featureCount":1,"checksum":"bad","bytes":12}},"totals":{"featureCount":1,"capacityMw":1}}'

    with pytest.raises(ValueError, match="unknown country"):
        publisher.publish("bad", invalid, {"snapshotId": "bad"})
    assert json.loads((tmp_path / "latest.json").read_text())["snapshotId"] == "first"


def test_publish_size_and_feature_guards_keep_last_good(tmp_path) -> None:
    publisher = SnapshotPublisher(tmp_path)
    publisher.publish("first", global_artifacts(), {"snapshotId": "first"})

    with pytest.raises(ValueError, match="artifact size guard"):
        publisher.publish(
            "too-large", global_artifacts(),
            {"snapshotId": "too-large", "guards": {"maxArtifactBytes": 8}},
        )
    with pytest.raises(ValueError, match="generator feature-count guard"):
        publisher.publish(
            "too-many", global_artifacts(),
            {"snapshotId": "too-many", "guards": {"maxGeneratorFeatures": -1}},
        )
    assert json.loads((tmp_path / "latest.json").read_text())["snapshotId"] == "first"


def test_publish_rejects_unsafe_nested_artifact_path(tmp_path) -> None:
    invalid = global_artifacts()
    invalid["../outside.json"] = b"{}"

    with pytest.raises(ValueError, match="unsafe artifact path"):
        SnapshotPublisher(tmp_path).publish("invalid", invalid, {"snapshotId": "invalid"})

    noncanonical = global_artifacts()
    noncanonical["nested//duplicate.json"] = b"{}"
    with pytest.raises(ValueError, match="unsafe artifact path"):
        SnapshotPublisher(tmp_path).publish(
            "noncanonical", noncanonical, {"snapshotId": "noncanonical"}
        )
