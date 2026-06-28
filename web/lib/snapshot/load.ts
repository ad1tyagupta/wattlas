import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  assetFeatureCollectionSchema,
  evidenceSchema,
  geographyFeatureCollectionSchema,
  manifestSchema,
} from "@/lib/snapshot/schema";
import type { SnapshotData } from "@/lib/snapshot/types";

async function readJson<T>(filePath: string): Promise<T> {
  return JSON.parse(await readFile(filePath, "utf8")) as T;
}

export async function loadSnapshot(): Promise<SnapshotData> {
  const publicData = path.join(process.cwd(), "public", "data");
  const manifest = manifestSchema.parse(
    await readJson(path.join(publicData, "latest.json")),
  );

  const [countriesRaw, regionsRaw, assetsRaw, evidenceRaw] = await Promise.all([
    readJson(path.join(publicData, manifest.artifacts.countries)),
    readJson(path.join(publicData, manifest.artifacts.regions)),
    readJson(path.join(publicData, manifest.artifacts.assets)),
    readJson(path.join(publicData, manifest.artifacts.evidence)),
  ]);

  const countries = geographyFeatureCollectionSchema.parse(countriesRaw);
  const regions = geographyFeatureCollectionSchema.parse(regionsRaw);
  const assets = assetFeatureCollectionSchema.parse(assetsRaw);
  const evidence = evidenceSchema.parse(evidenceRaw);
  const admin1 = { type: "FeatureCollection", features: [] } as SnapshotData["admin1"];
  return { manifest, countries, admin1, regions, assets, evidence } as SnapshotData;
}
