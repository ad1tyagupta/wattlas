import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  assetFeatureCollectionSchema,
  evidenceSchema,
  geographyFeatureCollectionSchema,
  manifestSchema,
} from "@/lib/snapshot/schema";
import type { SnapshotData, SnapshotManifest } from "@/lib/snapshot/types";

async function readJson<T>(filePath: string): Promise<T> {
  return JSON.parse(await readFile(filePath, "utf8")) as T;
}

function migrateLegacyContributions<T>(payload: T, modelVersion: string): T {
  const visit = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value) visit(item);
      return;
    }
    if (value === null || typeof value !== "object") return;
    const record = value as Record<string, unknown>;
    if (
      typeof record.id === "string" && typeof record.label === "string"
      && "points" in record && typeof record.normalization === "string"
      && !("methodVersion" in record)
    ) {
      record.methodVersion = `legacy-${modelVersion}`;
    }
    for (const child of Object.values(record)) visit(child);
  };
  visit(payload);
  return payload;
}

/** The deliberately small snapshot subset serialized into the initial RSC payload. */
export function serverSnapshotArtifactPaths(manifest: SnapshotManifest) {
  return {
    countries: manifest.artifacts.countries,
    regions: manifest.artifacts.regions,
    assets: manifest.artifacts.assets,
    evidence: manifest.artifacts.evidence,
  } as const;
}

export async function loadSnapshot(): Promise<SnapshotData> {
  const publicData = path.join(process.cwd(), "public", "data");
  const manifest = manifestSchema.parse(
    await readJson(path.join(publicData, "latest.json")),
  );

  const serverArtifacts = serverSnapshotArtifactPaths(manifest);
  const [countriesRaw, regionsRaw, assetsRaw, evidenceRaw] = await Promise.all([
    readJson(path.join(publicData, serverArtifacts.countries)),
    readJson(path.join(publicData, serverArtifacts.regions)),
    readJson(path.join(publicData, serverArtifacts.assets)),
    readJson(path.join(publicData, serverArtifacts.evidence)),
  ]);

  const countries = geographyFeatureCollectionSchema.parse(migrateLegacyContributions(countriesRaw, manifest.modelVersion));
  const regions = geographyFeatureCollectionSchema.parse(migrateLegacyContributions(regionsRaw, manifest.modelVersion));
  const assets = assetFeatureCollectionSchema.parse(assetsRaw);
  const evidence = evidenceSchema.parse(evidenceRaw);
  const admin1 = { type: "FeatureCollection", features: [] } as SnapshotData["admin1"];
  return { manifest, countries, admin1, regions, assets, evidence } as SnapshotData;
}
