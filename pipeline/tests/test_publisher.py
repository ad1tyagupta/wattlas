import json

import pytest

from grid_scope.publisher import SnapshotPublisher


def global_artifacts() -> dict[str, bytes]:
    return {
        "countries.geojson": b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"AE","geometry":{"type":"Polygon","coordinates":[]},"properties":{"id":"AE"}}]}',
        "regions.geojson": b'{"type":"FeatureCollection","features":[]}',
        "assets.geojson": b'{"type":"FeatureCollection","features":[]}',
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
