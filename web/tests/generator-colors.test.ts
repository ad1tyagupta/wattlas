import { describe, expect, it, vi } from "vitest";

import { GENERATOR_COLORS, generatorColor, generatorColorExpression } from "@/lib/map/generator-colors";
import { countriesInBounds, createGeneratorShardController, filterGenerators, generatorSelection } from "@/lib/map/generator-shards";
import type { GeneratorCollection, GeneratorIndex } from "@/lib/snapshot/types";

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
  });

  it("filters by technology and lifecycle", () => {
    const data = collection([
      feature("solar", "operational", "solar"),
      feature("wind", "announced", "wind"),
    ]);
    expect(filterGenerators(data, new Set(["solar"]), new Set(["operational"])).features.map((item) => item.id)).toEqual(["solar"]);
  });

  it("returns the typed generator entity selected by a map feature id", () => {
    const selected = generatorSelection(collection([feature("plant-1", "operational", "wind")]), "plant-1");
    expect(selected?.properties.category).toBe("power_generation");
    expect(selected?.properties.technologies).toEqual(["wind"]);
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
});

function collection(features: GeneratorCollection["features"]): GeneratorCollection { return { type: "FeatureCollection", features }; }
function feature(id: string, lifecycle: string, technology: "solar" | "wind"): GeneratorCollection["features"][number] {
  return { type: "Feature", id, geometry: { type: "Point", coordinates: [0, 0] }, properties: { id, category: "power_generation", country: "US", geographyId: "US-X", lifecycle, technologies: [technology], capacityMw: 1, operatingCapacityMw: 1, plannedCapacityMw: 0, technologyMixMw: { [technology]: 1 }, sourceIds: ["source"] } };
}
