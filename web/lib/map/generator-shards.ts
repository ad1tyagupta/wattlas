import { loadGeneratorCountry } from "@/lib/snapshot/generators";
import type { GenerationTechnology, GeneratorCollection, GeneratorFeature, GeneratorIndex, GeneratorOverviewCollection, LayerResult } from "@/lib/snapshot/types";

export type MapBounds = [west: number, south: number, east: number, north: number];
type CountryLoader = (root: string, index: GeneratorIndex, country: string, options?: { signal?: AbortSignal }) => Promise<LayerResult<GeneratorCollection>>;

const emptyCollection = (): GeneratorCollection => ({ type: "FeatureCollection", features: [] });
const longitudeSegments = (west: number, east: number): Array<[number, number]> => west <= east ? [[west, east]] : [[west, 180], [-180, east]];

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
  return {
    type: "FeatureCollection",
    features: data.features.filter(({ properties }) => properties.technologies.some((technology) => technologies.has(technology)) && (!properties.lifecycle || lifecycles.has(properties.lifecycle))),
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
      const selectedLifecycleCount = lifecycleCounts ? Object.entries(lifecycleCounts).reduce((sum, [state, count]) => sum + (lifecycles.has(state) ? (count ?? 0) : 0), 0) : null;
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

export function createGeneratorShardController(root: string, index: GeneratorIndex, loader: CountryLoader = loadGeneratorCountry, options: { concurrency?: number } = {}) {
  const cache = new Map<string, GeneratorCollection>();
  const pending = new Map<string, Promise<void>>();
  const controllers = new Map<string, AbortController>();
  const concurrency = Math.max(1, options.concurrency ?? 3);
  let revision = 0;
  let disposed = false;

  async function ensure(country: string, retry = true): Promise<void> {
    if (cache.has(country)) return;
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
