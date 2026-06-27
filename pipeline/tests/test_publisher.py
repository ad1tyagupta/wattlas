import json

import pytest

from grid_scope.publisher import SnapshotPublisher


def test_failed_publish_keeps_last_known_good(tmp_path) -> None:
    publisher = SnapshotPublisher(tmp_path)
    publisher.publish(
        "first",
        {"regions.geojson": b'{"type":"FeatureCollection","features":[]}'},
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
        {"regions.geojson": b'{"type":"FeatureCollection","features":[]}'},
        {"snapshotId": "first"},
    )

    manifest = json.loads((tmp_path / "snapshots" / "first" / "manifest.json").read_text())
    assert len(manifest["checksums"]["regions.geojson"]) == 64
