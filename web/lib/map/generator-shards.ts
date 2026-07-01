import { loadGeneratorCountry } from "@/lib/snapshot/generators";
import type { GenerationTechnology, GeneratorCollection, GeneratorFeature, GeneratorIndex, GeneratorOverviewCollection, LayerResult } from "@/lib/snapshot/types";

export type MapBounds = [west: number, south: number, east: number, north: number];
type CountryLoader = (root: string, index: GeneratorIndex, country: string, options?: { signal?: AbortSignal }) => Promise<LayerResult<GeneratorCollection>>;

const emptyCollection = (): GeneratorCollection => ({ type: "FeatureCollection", features: [] });
const normalizeLongitude = (longitude: number): number => ((longitude + 180) % 360 + 360) % 360 - 180;
function longitudeSegments(west: number, east: number): Array<[number, number]> {
  const rawSpan = east - west;
  if (Math.abs(rawSpan) >= 360) return [[-180, 180]];
  let span = rawSpan;
  while (span < 0) span += 360;
  if (span >= 360) return [[-180, 180]];
  const start = normalizeLongitude(west);
  const finish = start + span;
  return finish <= 180 ? [[start, finish]] : [[start, 180], [-180, finish - 360]];
}

export function countriesInBounds(index: GeneratorIndex, bounds: MapBounds): string[] {
  const [west, south, east, north] = bounds;
  const viewSegments = longitudeSegments(west, east);
  return Object.entries(index.countries).filter(([, entry]) => {
    if (entry.bbox[3] < south || entry.bbox[1] > north) return false;
    const countrySegments = longitudeSegments(entry.bbox[0], entry.bbox[2]);
    return viewSegments.some(([vWest, vEast]) => countrySegments.some(([cWest, cEast]) => cEast >= vWest && cWest <= vEast));
  }).map(([country]) => country).sort();
}

export function filterGenerators(data: GeneratorCollection, technologies: ReadonlySet<GenerationTechnology>, lifecycles: ReadonlySet<string>): GeneratorCollection {
  if (technologies.size === 0 || lifecycles.size === 0) return emptyCollection();
  return {
    type: "FeatureCollection",
    features: data.features.filter(({ properties }) => properties.technologies.some((technology) => technologies.has(technology)) && lifecycles.has(properties.lifecycle ?? "unknown")),
  };
}

const technologyLabel = (technology: GenerationTechnology) => technology.charAt(0).toUpperCase() + technology.slice(1);

export function filterGeneratorOverview(data: GeneratorOverviewCollection, technologies: ReadonlySet<GenerationTechnology>, lifecycles: ReadonlySet<string>): GeneratorOverviewCollection {
  if (lifecycles.size === 0) return { type: "FeatureCollection", features: [] };
  return {
    type: "FeatureCollection",
    features: data.features.flatMap((feature) => {
      const mix = Object.entries(feature.properties.technologyMixMw)
        .filter((entry): entry is [GenerationTechnology, number] => technologies.has(entry[0] as GenerationTechnology) && typeof entry[1] === "number" && entry[1] > 0)
        .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
      if (!mix.length) return [];
      const lifecycleCounts = feature.properties.lifecycleCounts;
      const classifiedLifecycleCount = lifecycleCounts ? Object.values(lifecycleCounts).reduce<number>((sum, count) => sum + (count ?? 0), 0) : 0;
      const unknownLifecycleCount = lifecycleCounts ? Math.max(0, feature.properties.count - classifiedLifecycleCount) : 0;
      const selectedLifecycleCount = lifecycleCounts
        ? Object.entries(lifecycleCounts).reduce<number>((sum, [state, count]) => sum + (lifecycles.has(state) ? (count ?? 0) : 0), lifecycles.has("unknown") ? unknownLifecycleCount : 0)
        : null;
      if (selectedLifecycleCount === 0) return [];
      const filteredCapacityMw = mix.reduce((sum, [, capacity]) => sum + capacity, 0);
      const isMixed = mix.length > 1;
      const compositionLabel = mix.map(([technology, capacity]) => `${technologyLabel(technology)} ${Math.round(capacity / filteredCapacityMw * 100)}%`).join(" · ");
      const lifecycleFilterExact = lifecycleCounts !== undefined && selectedLifecycleCount === feature.properties.count;
      const filterDisclosure = lifecycleFilterExact
        ? "Technology and lifecycle filters applied at aggregate resolution"
        : lifecycleCounts === undefined
          ? "Lifecycle counts unavailable at world zoom; capacity and technology mix remain unfiltered"
          : "Partial lifecycle filter is approximate at world zoom; capacity and technology mix remain unfiltered";
      return [{
        ...feature,
        properties: {
          ...feature.properties,
          technologyMixMw: Object.fromEntries(mix),
          dominantTechnology: mix[0][0],
          displayTechnology: isMixed ? "mixed" : mix[0][0],
          isMixed,
          filteredCapacityMw,
          compositionLabel,
          overviewLabel: lifecycleFilterExact ? compositionLabel : `${compositionLabel} · lifecycle approximate`,
          lifecycleFilterExact,
          filterDisclosure,
        },
      }];
    }),
  };
}

export function generatorSelection(data: GeneratorCollection, id: string | number | undefined): GeneratorFeature | null {
  if (typeof id !== "string") return null;
  return (data.features.find((feature) => feature.properties.id === id) as GeneratorFeature | undefined) ?? null;
}

export function createGeneratorShardController(root: string, index: GeneratorIndex, loader: CountryLoader = loadGeneratorCountry, options: { concurrency?: number; maxCountries?: number; maxFeatures?: number } = {}) {
  const cache = new Map<string, GeneratorCollection>();
  const pending = new Map<string, Promise<void>>();
  const controllers = new Map<string, AbortController>();
  const concurrency = Math.max(1, options.concurrency ?? 3);
  const maxCountries = Math.max(1, options.maxCountries ?? 12);
  const maxFeatures = Math.max(1, options.maxFeatures ?? 100_000);
  let revision = 0;
  let disposed = false;

  async function ensure(country: string, retry = true): Promise<void> {
    const cached = cache.get(country);
    if (cached) {
      cache.delete(country);
      cache.set(country, cached);
      return;
    }
    const existing = pending.get(country);
    if (existing) {
      await existing;
      if (!cache.has(country) && retry) await ensure(country, false);
      return;
    }
    const controller = new AbortController();
    controllers.set(country, controller);
    const request = loader(root, index, country, { signal: controller.signal }).then((result) => {
      if (result.ok) cache.set(country, result.data);
    }).finally(() => {
      pending.delete(country);
      controllers.delete(country);
    });
    pending.set(country, request);
    return request;
  }

  return {
    async show(countries: readonly string[]): Promise<GeneratorCollection> {
      if (disposed) return emptyCollection();
      const requestRevision = ++revision;
      const visible = [...new Set(countries)].filter((country) => country in index.countries);
      for (const [country, controller] of controllers) if (!visible.includes(country)) controller.abort();
      let cursor = 0;
      await Promise.all(Array.from({ length: Math.min(concurrency, visible.length) }, async () => {
        while (cursor < visible.length) await ensure(visible[cursor++]);
      }));
      if (disposed || requestRevision !== revision) return emptyCollection();
      let retainedFeatures = [...cache.values()].reduce((sum, collection) => sum + collection.features.length, 0);
      while (cache.size > maxCountries || retainedFeatures > maxFeatures) {
        const candidate = [...cache.keys()].find((country) => !visible.includes(country) && !pending.has(country));
        if (!candidate) break;
        retainedFeatures -= cache.get(candidate)?.features.length ?? 0;
        cache.delete(candidate);
      }
      return { type: "FeatureCollection", features: visible.flatMap((country) => cache.get(country)?.features ?? []) };
    },
    dispose() {
      disposed = true;
      revision += 1;
      for (const controller of controllers.values()) controller.abort();
      controllers.clear();
    },
  };
}
