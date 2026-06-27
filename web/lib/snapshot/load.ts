import { readFile } from "node:fs/promises";
import path from "node:path";

import { manifestSchema } from "@/lib/snapshot/schema";
import type { SnapshotData } from "@/lib/snapshot/types";

async function readJson<T>(filePath: string): Promise<T> {
  return JSON.parse(await readFile(filePath, "utf8")) as T;
}

export async function loadSnapshot(): Promise<SnapshotData> {
  const publicData = path.join(process.cwd(), "public", "data");
  const manifest = manifestSchema.parse(
    await readJson(path.join(publicData, "latest.json")),
  );

  const [regions, projects, evidence] = await Promise.all([
    readJson(path.join(publicData, manifest.artifacts.regions)),
    readJson(path.join(publicData, manifest.artifacts.projects)),
    readJson(path.join(publicData, manifest.artifacts.evidence)),
  ]);

  return { manifest, regions, projects, evidence } as SnapshotData;
}
