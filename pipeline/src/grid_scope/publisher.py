from __future__ import annotations

import json
import os
import shutil
from hashlib import sha256
from pathlib import Path


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
        if "regions.geojson" not in artifacts:
            raise ValueError("regions.geojson is required for publication")

        temporary = self.snapshots_dir / f"{snapshot_id}.tmp"
        destination = self.snapshots_dir / snapshot_id
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)

        checksums: dict[str, str] = {}
        for filename, body in artifacts.items():
            (temporary / filename).write_bytes(body)
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
