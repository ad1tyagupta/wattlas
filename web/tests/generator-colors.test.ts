import { describe, expect, it, vi } from "vitest";

import { GENERATOR_COLORS, generatorColor, generatorColorExpression } from "@/lib/map/generator-colors";
import { countriesInBounds, createGeneratorShardController, filterGeneratorOverview, filterGenerators, generatorSelection } from "@/lib/map/generator-shards";
import type { GeneratorCollection, GeneratorIndex, GeneratorOverviewCollection } from "@/lib/snapshot/types";

describe("generator semantics", () => {
  it("uses the approved technology palette", () => {
    expect(generatorColor("solar")).toBe("#E7B84B");
    expect(generatorColor("wind")).toBe("#55C7D9");
    expect(generatorColor("hydro")).toBe("#4E8EDB");
    expect(generatorColor("nuclear")).toBe("#A98AE8");
    expect(Object.keys(GENERATOR_COLORS)).toEqual(["solar", "wind", "hydro", "nuclear", "gas", "coal", "oil", "biomass", "geothermal", "other"]);
    expect(new Set(Object.values(GENERATOR_COLORS)).size).toBe(10);
    expect(generatorColorExpression()).toContain("#E7B84B");
  });

  it("selects visible countries across ordinary and antimeridian bounds", () => {
    const index = { countries: {
      US: { bbox: [-125, 24, -66, 49], path: "generators/US.geojson", featureCount: 1, checksum: "a".repeat(64), bytes: 1, capacityMw: 1 },
      FJ: { bbox: [177, -20, -178, -12], path: "generators/FJ.geojson", featureCount: 1, checksum: "b".repeat(64), bytes: 1, capacityMw: 1 },
    }, totals: { featureCount: 2, capacityMw: 2 } } satisfies GeneratorIndex;
    expect(countriesInBounds(index, [-130, 20, -60, 55])).toEqual(["US"]);
    expect(countriesInBounds(index, [170, -30, -170, 0])).toEqual(["FJ"]);
    expect(countriesInBounds(index, [170, -30, 190, 55])).toEqual(["FJ"]);
    expect(countriesInBounds(index, [-190, -30, -170, 55])).toEqual(["FJ"]);
    expect(countriesInBounds(index, [190, 20, 294, 55])).toEqual(["US"]);
    expect(countriesInBounds(index, [-540, -90, 540, 90])).toEqual(["FJ", "US"]);
    expect(countriesInBounds(index, [180, -90, 540, 90])).toEqual(["FJ", "US"]);
  });

  it("filters by technology and lifecycle", () => {
    const data = collection([
      feature("solar", "operational", "solar"),
      feature("wind", "announced", "wind"),
    ]);
    expect(filterGenerators(data, new Set(["solar"]), new Set(["operational"])).features.map((item) => item.id)).toEqual(["solar"]);
    expect(filterGenerators(collection([feature("missing", undefined, "solar")]), new Set(["solar"]), new Set()).features).toHaveLength(0);
    expect(filterGenerators(data, new Set(["solar", "wind"]), new Set()).features).toHaveLength(0);
    expect(filterGenerators(collection([feature("missing", undefined, "solar")]), new Set(["solar"]), new Set(["unknown"])).features.map((item) => item.id)).toEqual(["missing"]);
  });

  it("returns the typed generator entity selected by a map feature id", () => {
    const selected = generatorSelection(collection([feature("plant-1", "operational", "wind")]), "plant-1");
    expect(selected?.properties.category).toBe("power_generation");
    expect(selected?.properties.technologies).toEqual(["wind"]);
  });

  it("filters overview technology mix and marks mixed composition honestly", () => {
    const overview = overviewCollection({ solar: 60, wind: 40 }, { operational: 2 });
    const filtered = filterGeneratorOverview(overview, new Set(["solar", "wind"]), new Set(["operational"]));
    expect(filtered.features[0].properties).toMatchObject({
      dominantTechnology: "solar", displayTechnology: "mixed", isMixed: true,
      filteredCapacityMw: 100, compositionLabel: "Solar 60% · Wind 40%", lifecycleFilterExact: true,
    });
    expect(filterGeneratorOverview(overview, new Set(["hydro"]), new Set(["operational"])).features).toHaveLength(0);
    expect(filterGeneratorOverview(overview, new Set(["solar"]), new Set(["retired"])).features).toHaveLength(0);
  });

  it("retains lifecycle aggregates without counts and labels the filter as inexact", () => {
    const overview = overviewCollection({ solar: 100 });
    const filtered = filterGeneratorOverview(overview, new Set(["solar"]), new Set(["operational"]));
    expect(filtered.features[0].properties).toMatchObject({ lifecycleFilterExact: false, filterDisclosure: "Lifecycle counts unavailable at world zoom; capacity and technology mix remain unfiltered", overviewLabel: "Solar 100% · lifecycle approximate" });
    expect(filterGeneratorOverview(overview, new Set(["solar"]), new Set()).features).toHaveLength(0);
  });

  it("retains unfiltered world mix for a partial lifecycle match and discloses approximation", () => {
    const overview = overviewCollection({ solar: 60, wind: 40 }, { operational: 1, retired: 1 });
    const filtered = filterGeneratorOverview(overview, new Set(["solar", "wind"]), new Set(["operational"]));
    expect(filtered.features).toHaveLength(1);
    expect(filtered.features[0].properties).toMatchObject({
      lifecycleFilterExact: false,
      filteredCapacityMw: 100,
      technologyMixMw: { solar: 60, wind: 40 },
      filterDisclosure: "Partial lifecycle filter is approximate at world zoom; capacity and technology mix remain unfiltered",
      overviewLabel: "Solar 60% · Wind 40% · lifecycle approximate",
    });
  });

  it("treats unclassified lifecycle records consistently at detail and overview zooms", () => {
    const overview = overviewCollection({ solar: 100 }, { operational: 1 });
    const unknownOnly = filterGeneratorOverview(overview, new Set(["solar"]), new Set(["unknown"]));
    expect(unknownOnly.features[0].properties).toMatchObject({ lifecycleFilterExact: false });
    const all = filterGeneratorOverview(overview, new Set(["solar"]), new Set(["operational", "unknown"]));
    expect(all.features[0].properties).toMatchObject({ lifecycleFilterExact: true });
  });

  it("fetches each immutable shard once, combines visible cached shards, and drops only rendered data", async () => {
    const index = { countries: {
      US: { bbox: [-125, 24, -66, 49], path: "generators/US.geojson", featureCount: 1, checksum: "a".repeat(64), bytes: 1, capacityMw: 1 },
      DE: { bbox: [5, 47, 15, 55], path: "generators/DE.geojson", featureCount: 1, checksum: "b".repeat(64), bytes: 1, capacityMw: 1 },
    }, totals: { featureCount: 2, capacityMw: 2 } } satisfies GeneratorIndex;
    const load = vi.fn(async (_root: string, _index: GeneratorIndex, country: string) => ({ ok: true as const, data: collection([feature(country, "operational", "solar")]) }));
    const controller = createGeneratorShardController("snapshots/id", index, load, { concurrency: 2 });
    expect((await controller.show(["US", "DE"])).features).toHaveLength(2);
    expect((await controller.show(["US"])).features.map((item) => item.id)).toEqual(["US"]);
    expect((await controller.show([])).features).toHaveLength(0);
    expect((await controller.show(["DE"])).features.map((item) => item.id)).toEqual(["DE"]);
    expect(load).toHaveBeenCalledTimes(2);
    controller.dispose();
  });

  it("bounds decoded shard memory with LRU while preserving every active country", async () => {
    const countries = Object.fromEntries(["AA", "BB", "CC", "DD"].map((country) => [country, { bbox: [0, 0, 1, 1] as [number, number, number, number], path: `generators/${country}.geojson`, featureCount: 1, checksum: country.toLowerCase().repeat(32), bytes: 1, capacityMw: 1 }]));
    const index = { countries, totals: { featureCount: 4, capacityMw: 4 } } satisfies GeneratorIndex;
    const load = vi.fn(async (_root: string, _index: GeneratorIndex, country: string) => ({ ok: true as const, data: collection([feature(country, "operational", "solar")]) }));
    const controller = createGeneratorShardController("snapshots/id", index, load, { maxCountries: 2, maxFeatures: 2 });
    await controller.show(["AA"]); await controller.show(["BB"]); await controller.show(["CC"]);
    await controller.show(["BB"]);
    expect(load.mock.calls.filter((call) => call[2] === "BB")).toHaveLength(1);
    await controller.show(["AA"]);
    expect(load.mock.calls.filter((call) => call[2] === "AA")).toHaveLength(2);
    await controller.show(["CC", "DD", "BB"]);
    await controller.show(["BB"]);
    expect(load.mock.calls.filter((call) => call[2] === "BB")).toHaveLength(1);
    controller.dispose();
  });
});

function collection(features: GeneratorCollection["features"]): GeneratorCollection { return { type: "FeatureCollection", features }; }
function feature(id: string, lifecycle: string | undefined, technology: "solar" | "wind"): GeneratorCollection["features"][number] {
  return { type: "Feature", id, geometry: { type: "Point", coordinates: [0, 0] }, properties: { id, category: "power_generation", country: "US", geographyId: "US-X", lifecycle, technologies: [technology], capacityMw: 1, operatingCapacityMw: 1, plannedCapacityMw: 0, technologyMixMw: { [technology]: 1 }, sourceIds: ["source"] } };
}
function overviewCollection(technologyMixMw: Record<string, number>, lifecycleCounts?: Record<string, number>): GeneratorOverviewCollection {
  return { type: "FeatureCollection", features: [{ type: "Feature", id: "US-X", geometry: { type: "Point", coordinates: [0, 0] }, properties: { geographyId: "US-X", country: "US", count: 2, capacityMw: 100, operatingCapacityMw: 100, plannedCapacityMw: 0, technologyMixMw, dominantTechnology: "solar", lifecycleCounts } }] } as GeneratorOverviewCollection;
}
