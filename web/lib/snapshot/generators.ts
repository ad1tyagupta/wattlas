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

const immutablePathCache = new Map<string, CacheEntry<unknown>>();

function layerError(path: string, error: unknown): LayerError {
  if (error instanceof DOMException && error.name === "AbortError") {
    return { kind: "aborted", message: "Layer request was superseded", recoverable: true, path };
  }
  if (error instanceof z.ZodError) {
    return { kind: "invalid", message: "Layer response did not match its published contract", recoverable: true, path };
  }
  if (error instanceof Error && /^Layer request failed \(\d+\)$/.test(error.message)) {
    return { kind: "http", message: error.message, recoverable: true, path };
  }
  return { kind: "network", message: error instanceof Error ? error.message : "Layer request failed", recoverable: true, path };
}

async function requestLayer<T>(path: string, schema: z.ZodType<T>, signal: AbortSignal): Promise<LayerResult<T>> {
  const response = await fetch(path.startsWith("/") ? path : `/data/${path}`, { signal });
  if (!response.ok) throw new Error(`Layer request failed (${response.status})`);
  return { ok: true, data: schema.parse(await response.json()) };
}

function loadLayer<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal): Promise<LayerResult<T>> {
  const existing = immutablePathCache.get(path) as CacheEntry<T> | undefined;
  if (existing) return observeWithSignal(existing, path, signal);
  const controller = new AbortController();
  const entry: CacheEntry<T> = {
    controller,
    observers: 0,
    settled: false,
    promise: Promise.resolve({ ok: false, error: layerError(path, new Error("Layer request not started")) }),
  };
  entry.promise = requestLayer(path, schema, controller.signal)
    .catch((error: unknown): LayerResult<T> => ({ ok: false, error: layerError(path, error) }))
    .then((result) => {
      entry.settled = true;
      if (!result.ok && immutablePathCache.get(path) === entry) immutablePathCache.delete(path);
      return result;
    });
  immutablePathCache.set(path, entry as CacheEntry<unknown>);
  return observeWithSignal(entry, path, signal);
}

function observeWithSignal<T>(entry: CacheEntry<T>, path: string, signal?: AbortSignal): Promise<LayerResult<T>> {
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
        if (immutablePathCache.get(path) === entry) immutablePathCache.delete(path);
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
  return loadLayer(path, geographyFeatureCollectionSchema, options.signal);
}

export function loadRegionalEnergy(path: string, options: { signal?: AbortSignal } = {}): Promise<LayerResult<RegionalEnergyData>> {
  return loadLayer(path, regionalEnergySchema, options.signal);
}

export function loadGeneratorOverview(path: string, options: { signal?: AbortSignal } = {}): Promise<LayerResult<GeneratorOverviewCollection>> {
  return loadLayer(path, generatorOverviewSchema, options.signal);
}

export function loadGeneratorIndex(path: string, options: { signal?: AbortSignal } = {}): Promise<LayerResult<GeneratorIndex>> {
  return loadLayer(path, generatorIndexSchema, options.signal);
}

export function loadGeneratorCountry(
  snapshotRoot: string,
  index: GeneratorIndex,
  country: string,
  options: { signal?: AbortSignal } = {},
): Promise<LayerResult<GeneratorCollection>> {
  const normalizedCountry = country.toUpperCase();
  const entry = index.countries[normalizedCountry];
  if (!entry) {
    const path = `${snapshotRoot}/generators/${normalizedCountry}.geojson`;
    return Promise.resolve({ ok: false, error: { kind: "missing", message: `No generator shard is published for ${normalizedCountry}`, recoverable: true, path } });
  }
  const root = snapshotRoot.replace(/^\/+|\/+$/g, "");
  return loadLayer(`${root}/${entry.path}`, generatorCountryShardSchema, options.signal);
}
