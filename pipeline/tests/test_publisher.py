import json

import pytest

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
