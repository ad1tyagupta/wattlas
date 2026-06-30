import { z } from "zod";

import {
  generatorCountryShardSchema,
  generatorIndexSchema,
  generatorOverviewSchema,
  geographyFeatureCollectionSchema,
  regionalEnergySchema,
} from "@/lib/snapshot/schema";
import type {
  GeneratorCollection,
  GeneratorIndex,
  GeneratorOverviewCollection,
  GeographyCollection,
  LayerError,
  LayerResult,
  RegionalEnergyData,
} from "@/lib/snapshot/types";

type CacheEntry<T> = {
  promise: Promise<LayerResult<T>>;
  controller: AbortController;
  observers: number;
  settled: boolean;
};

type IntegrityExpectation = { bytes: number; checksum: string; featureCount: number };
type LayerKind = "admin1" | "regional-energy" | "generator-overview" | "generator-index" | "generator-country";

const MAX_CACHE_ENTRIES = 32;
const MAX_BYTES: Record<LayerKind, number> = {
  admin1: 64 * 1024 * 1024,
  "regional-energy": 48 * 1024 * 1024,
  "generator-overview": 16 * 1024 * 1024,
  "generator-index": 2 * 1024 * 1024,
  "generator-country": 32 * 1024 * 1024,
};
const MAX_COUNTRY_FEATURES = 250_000;
const immutablePathCache = new Map<string, CacheEntry<unknown>>();

class LayerFailure extends Error {
  constructor(readonly kind: "invalid" | "http", message: string) {
    super(message);
  }
}

function canonicalArtifactPath(path: string): string {
  if (
    path.startsWith("/") || path.includes("\\") || path.includes("?") || path.includes("#")
    || path.includes("//") || path.endsWith("/")
  ) throw new LayerFailure("invalid", "Layer path is not canonical");
  const parts = path.split("/");
  if (parts.length < 3 || parts[0] !== "snapshots" || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(parts[1])) {
    throw new LayerFailure("invalid", "Layer path must be contained in a snapshot");
  }
  if (parts.some((part) => !part || part === "." || part === ".." || !/^[A-Za-z0-9._-]+$/.test(part))) {
    throw new LayerFailure("invalid", "Layer path contains an unsafe segment");
  }
  return parts.join("/");
}

function canonicalSnapshotRoot(root: string): string {
  const parts = root.split("/");
  if (parts.length !== 2) throw new LayerFailure("invalid", "Snapshot root must identify exactly one snapshot");
  return canonicalArtifactPath(`${root}/placeholder.json`).slice(0, -"/placeholder.json".length);
}

function contentTypeIsJson(value: string | null): boolean {
  if (!value) return false;
  const mediaType = value.split(";", 1)[0].trim().toLowerCase();
  return mediaType === "application/json" || mediaType === "application/geo+json" || mediaType.endsWith("+json");
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", Uint8Array.from(bytes).buffer);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function layerError(path: string, error: unknown): LayerError {
  if (error instanceof DOMException && error.name === "AbortError") {
    return { kind: "aborted", message: "Layer request was superseded", recoverable: true, path };
  }
  if (error instanceof z.ZodError) {
    return { kind: "invalid", message: "Layer response did not match its published contract", recoverable: true, path };
  }
  if (error instanceof LayerFailure) {
    return { kind: error.kind, message: error.message, recoverable: true, path };
  }
  return { kind: "network", message: error instanceof Error ? error.message : "Layer request failed", recoverable: true, path };
}

async function requestLayer<T>(
  path: string,
  schema: z.ZodType<T>,
  signal: AbortSignal,
  maxBytes: number,
  integrity?: IntegrityExpectation,
): Promise<LayerResult<T>> {
  const response = await fetch(`/data/${path}`, { signal });
  if (!response.ok) throw new LayerFailure("http", `Layer request failed (${response.status})`);
  if (!contentTypeIsJson(response.headers.get("content-type"))) {
    throw new LayerFailure("invalid", "Layer response is not JSON");
  }
  const advertised = response.headers.get("content-length");
  if (advertised !== null && (!/^\d+$/.test(advertised) || Number(advertised) > maxBytes)) {
    throw new LayerFailure("invalid", "Layer response exceeds its byte limit");
  }
  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength > maxBytes) throw new LayerFailure("invalid", "Layer response exceeds its byte limit");
  if (integrity && bytes.byteLength !== integrity.bytes) throw new LayerFailure("invalid", "Generator shard byte count does not match its index");
  if (integrity && await sha256Hex(bytes) !== integrity.checksum) throw new LayerFailure("invalid", "Generator shard checksum does not match its index");
  let decoded: unknown;
  try {
    decoded = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new LayerFailure("invalid", "Layer response is not valid UTF-8 JSON");
  }
  const data = schema.parse(decoded);
  if (integrity && (data as GeneratorCollection).features.length !== integrity.featureCount) {
    throw new LayerFailure("invalid", "Generator shard feature count does not match its index");
  }
  return { ok: true, data };
}

function loadLayer<T>(kind: LayerKind, rawPath: string, schema: z.ZodType<T>, signal?: AbortSignal, integrity?: IntegrityExpectation): Promise<LayerResult<T>> {
  let path: string;
  try {
    path = canonicalArtifactPath(rawPath);
  } catch (error) {
    return Promise.resolve({ ok: false, error: layerError(rawPath, error) });
  }
  const cacheKey = `${kind}:${path}${integrity ? `:${integrity.checksum}:${integrity.bytes}:${integrity.featureCount}` : ""}`;
  const existing = immutablePathCache.get(cacheKey) as CacheEntry<T> | undefined;
  if (existing) {
    immutablePathCache.delete(cacheKey);
    immutablePathCache.set(cacheKey, existing as CacheEntry<unknown>);
    return observeWithSignal(existing, cacheKey, path, signal);
  }
  const controller = new AbortController();
  const entry: CacheEntry<T> = {
    controller,
    observers: 0,
    settled: false,
    promise: Promise.resolve({ ok: false, error: layerError(path, new Error("Layer request not started")) }),
  };
  entry.promise = requestLayer(path, schema, controller.signal, MAX_BYTES[kind], integrity)
    .catch((error: unknown): LayerResult<T> => ({ ok: false, error: layerError(path, error) }))
    .then((result) => {
      entry.settled = true;
      if (!result.ok && immutablePathCache.get(cacheKey) === entry) immutablePathCache.delete(cacheKey);
      return result;
    });
  immutablePathCache.set(cacheKey, entry as CacheEntry<unknown>);
  while (immutablePathCache.size > MAX_CACHE_ENTRIES) {
    const oldestKey = immutablePathCache.keys().next().value as string;
    const oldest = immutablePathCache.get(oldestKey);
    oldest?.controller.abort();
    immutablePathCache.delete(oldestKey);
  }
  return observeWithSignal(entry, cacheKey, path, signal);
}

function observeWithSignal<T>(entry: CacheEntry<T>, cacheKey: string, path: string, signal?: AbortSignal): Promise<LayerResult<T>> {
  if (signal?.aborted) {
    return Promise.resolve({ ok: false, error: layerError(path, new DOMException("stale", "AbortError")) });
  }
  entry.observers += 1;
  return new Promise((resolve) => {
    let finished = false;
    const release = () => {
      if (finished) return;
      finished = true;
      entry.observers -= 1;
      if (!entry.settled && entry.observers === 0) {
        entry.controller.abort();
        if (immutablePathCache.get(cacheKey) === entry) immutablePathCache.delete(cacheKey);
      }
    };
    const abort = () => {
      release();
      resolve({ ok: false, error: layerError(path, new DOMException("stale", "AbortError")) });
    };
    signal?.addEventListener("abort", abort, { once: true });
    void entry.promise.then((result) => {
      signal?.removeEventListener("abort", abort);
      if (finished) return;
      release();
      resolve(result);
    });
  });
}

export function clearSnapshotLayerCache(): void {
  for (const entry of immutablePathCache.values()) entry.controller.abort();
  immutablePathCache.clear();
}

export function loadAdmin1(path: string, options: { signal?: AbortSignal } = {}): Promise<LayerResult<GeographyCollection>> {
  return loadLayer("admin1", path, geographyFeatureCollectionSchema, options.signal);
}

export function loadRegionalEnergy(path: string, options: { signal?: AbortSignal } = {}): Promise<LayerResult<RegionalEnergyData>> {
  return loadLayer("regional-energy", path, regionalEnergySchema, options.signal);
}

export function loadGeneratorOverview(path: string, options: { signal?: AbortSignal } = {}): Promise<LayerResult<GeneratorOverviewCollection>> {
  return loadLayer("generator-overview", path, generatorOverviewSchema, options.signal);
}

export function loadGeneratorIndex(path: string, options: { signal?: AbortSignal } = {}): Promise<LayerResult<GeneratorIndex>> {
  return loadLayer("generator-index", path, generatorIndexSchema, options.signal);
}

export function loadGeneratorCountry(
  snapshotRoot: string,
  index: GeneratorIndex,
  country: string,
  options: { signal?: AbortSignal } = {},
): Promise<LayerResult<GeneratorCollection>> {
  let root: string;
  try {
    root = canonicalSnapshotRoot(snapshotRoot);
  } catch (error) {
    return Promise.resolve({ ok: false, error: layerError(snapshotRoot, error) });
  }
  const normalizedCountry = country.toUpperCase();
  const entry = index.countries[normalizedCountry];
  if (!entry) {
    const path = `${root}/generators/${normalizedCountry}.geojson`;
    return Promise.resolve({ ok: false, error: { kind: "missing", message: `No generator shard is published for ${normalizedCountry}`, recoverable: true, path } });
  }
  if (entry.bytes > MAX_BYTES["generator-country"] || entry.featureCount > MAX_COUNTRY_FEATURES) {
    const shardPath = `${root}/${entry.path}`;
    return Promise.resolve({ ok: false, error: layerError(shardPath, new LayerFailure("invalid", "Generator shard exceeds client safety limits")) });
  }
  return loadLayer("generator-country", `${root}/${entry.path}`, generatorCountryShardSchema, options.signal, {
    bytes: entry.bytes, checksum: entry.checksum, featureCount: entry.featureCount,
  });
}
