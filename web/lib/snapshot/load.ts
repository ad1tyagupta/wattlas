import { readFile, realpath } from "node:fs/promises";
import path from "node:path";

import {
  assetFeatureCollectionSchema,
  evidenceSchema,
  geographyFeatureCollectionSchema,
  manifestSchema,
} from "@/lib/snapshot/schema";
import type { SnapshotData, SnapshotManifest } from "@/lib/snapshot/types";
import { migrateLegacyContributions } from "@/lib/snapshot/legacy";

async function readJson<T>(filePath: string): Promise<T> {
  return JSON.parse(await readFile(filePath, "utf8")) as T;
}

async function readJsonContained<T>(root: string, relativePath: string): Promise<T> {
  const [resolvedRoot, resolvedFile] = await Promise.all([realpath(root), realpath(path.join(root, relativePath))]);
  if (!resolvedFile.startsWith(`${resolvedRoot}${path.sep}`)) throw new Error("Snapshot artifact resolves outside public data");
  return readJson<T>(resolvedFile);
}

/** The deliberately small snapshot subset serialized into the initial RSC payload. */
export function serverSnapshotArtifactPaths(manifest: SnapshotManifest) {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(manifest.snapshotId) || manifest.snapshotId === "." || manifest.snapshotId === "..") {
    throw new Error("Snapshot ID is not a safe path segment");
  }
  const artifacts = {
    countries: manifest.artifacts.countries,
    regions: manifest.artifacts.regions,
    assets: manifest.artifacts.assets,
    evidence: manifest.artifacts.evidence,
  } as const;
  for (const [name, artifactPath] of Object.entries(artifacts)) {
    const extension = name === "evidence" ? "json" : "geojson";
    const expected = `snapshots/${manifest.snapshotId}/${name}.${extension}`;
    if (artifactPath !== expected) throw new Error(`Snapshot artifact path must be ${expected}`);
  }
  return artifacts;
}

export async function loadSnapshot(): Promise<SnapshotData> {
  const publicData = path.join(process.cwd(), "public", "data");
  const manifest = manifestSchema.parse(
    await readJson(path.join(publicData, "latest.json")),
  );

  const serverArtifacts = serverSnapshotArtifactPaths(manifest);
  const [countriesRaw, regionsRaw, assetsRaw, evidenceRaw] = await Promise.all([
    readJsonContained(publicData, serverArtifacts.countries),
    readJsonContained(publicData, serverArtifacts.regions),
    readJsonContained(publicData, serverArtifacts.assets),
    readJsonContained(publicData, serverArtifacts.evidence),
  ]);

  const legacyContributions = manifest.modelVersion === "2.1.0" && manifest.artifacts.regionalEnergy === undefined;
  const countries = geographyFeatureCollectionSchema.parse(migrateLegacyContributions(countriesRaw, manifest.modelVersion, legacyContributions));
  const regions = geographyFeatureCollectionSchema.parse(migrateLegacyContributions(regionsRaw, manifest.modelVersion, legacyContributions));
  const assets = assetFeatureCollectionSchema.parse(assetsRaw);
  const evidence = evidenceSchema.parse(evidenceRaw);
  const admin1 = { type: "FeatureCollection", features: [] } as SnapshotData["admin1"];
  return { manifest, countries, admin1, regions, assets, evidence } as SnapshotData;
}
