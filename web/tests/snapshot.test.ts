import { afterEach, describe, expect, it, vi } from "vitest";

import {
  assetPropertiesSchema,
  generatorCountryShardSchema,
  generatorIndexSchema,
  generatorOverviewSchema,
  geographyPropertiesSchema,
  manifestSchema,
  regionalEnergySchema,
} from "@/lib/snapshot/schema";
import { loadSnapshot, serverSnapshotArtifactPaths } from "@/lib/snapshot/load";
import {
  clearSnapshotLayerCache,
  loadAdmin1,
  loadGeneratorCountry,
  loadGeneratorIndex,
  loadGeneratorOverview,
  loadRegionalEnergy,
} from "@/lib/snapshot/generators";

const validManifest = {
  snapshotId: "2026-06-27T04-12-00Z",
  generatedAt: "2026-06-27T04:12:00Z",
  modelVersion: "1.0.0",
  activeYears: [2026, 2027, 2028, 2029, 2030, 2031],
  artifacts: {
    countries: "countries.geojson",
    admin1: "admin1.geojson",
    regions: "regions.geojson",
    assets: "assets.geojson",
    evidence: "evidence.json",
    regionalEnergy: "regional-energy.json",
    generatorOverview: "generator-overview.geojson",
    generatorIndex: "generators/index.json",
  },
  coverage: {
    countries: 246,
    regions: 334,
    admin1Regions: 3229,
    countriesWithAdmin1: 197,
    assets: 14,
    dataCentres: 8,
    waterInfrastructure: 6,
  },
  boundaryDisclaimer: "UN boundary disclaimer",
  connectors: [
    {
      id: "gisco",
      state: "current",
      checkedAt: "2026-06-27T04:11:00Z",
      lastSuccessAt: "2026-06-27T04:11:00Z",
      message: null,
    },
  ],
};

describe("snapshot manifest", () => {
  it("accepts the six-year snapshot contract", () => {
    expect(manifestSchema.parse(validManifest).activeYears).toHaveLength(6);
  });

  it("keeps ADM1, regional energy, and generator layers out of the server payload", () => {
    const manifest = manifestSchema.parse(validManifest);
    expect(serverSnapshotArtifactPaths(manifest)).toEqual({
      countries: "countries.geojson", regions: "regions.geojson",
      assets: "assets.geojson", evidence: "evidence.json",
    });
  });

  it("rejects an invalid connector state", () => {
    expect(() =>
      manifestSchema.parse({
        ...validManifest,
        connectors: [{ ...validManifest.connectors[0], state: "live" }],
      }),
    ).toThrow();
  });

  it("rejects a horizon outside 2026–2031", () => {
    expect(() =>
      manifestSchema.parse({ ...validManifest, activeYears: [2026, 2027, 2028] }),
    ).toThrow();
  });
});

describe("power balance snapshot contracts", () => {
  const range = { low: 90, central: 100, high: 115 };
  const forecast = {
    geographyId: "US-CA", year: 2030,
    metrics: {
      demandGwh: range, localGenerationGwh: { low: 70, central: 80, high: 90 },
      localGenerationGapGwh: { low: 0, central: 20, high: 45 },
      netBalanceGwh: { low: -35, central: -10, high: 10 },
      observedUnmetDemandGwh: 3, installedCapacityMw: 25,
      dependableCapacityMw: { low: 10, central: 12, high: 15 }, peakDemandMw: range,
    },
    powerBalance: { score: 58, coverage: 80, status: "rankable", contributions: [] },
    methodId: "regional-power-balance-v1", sourceIds: ["public-source"],
    confidence: 70, coverage: 80, valueKind: "estimated", appliedIncrementIds: [], metricLineage: {},
  };

  it("accepts signed balances while keeping local gap and observed unmet distinct", () => {
    const parsed = regionalEnergySchema.parse({ "US-CA": Array.from({ length: 6 }, (_, i) => ({ ...forecast, year: 2026 + i })) });
    expect(parsed["US-CA"][4].metrics.netBalanceGwh?.central).toBe(-10);
    expect(parsed["US-CA"][4].metrics.localGenerationGapGwh?.central).toBe(20);
    expect(parsed["US-CA"][4].metrics.observedUnmetDemandGwh).toBe(3);
  });

  it("accepts the compact Task 9 forecast shape without contribution internals", () => {
    const compact = { ...forecast, powerBalance: { score: 58, coverage: 80, status: "rankable" } };
    const parsed = regionalEnergySchema.parse({ "US-CA": Array.from({ length: 6 }, (_, i) => ({ ...compact, year: 2026 + i })) });
    expect(parsed["US-CA"][0].powerBalance?.contributions).toEqual([]);
  });

  it("rejects unordered ranges and dates outside the forecast horizon", () => {
    expect(() => regionalEnergySchema.parse({ "US-CA": [{ ...forecast, year: 2032 }] })).toThrow();
    expect(() => regionalEnergySchema.parse({ "US-CA": [{ ...forecast, metrics: { ...forecast.metrics, netBalanceGwh: { low: 2, central: 1, high: 3 } } }] })).toThrow();
  });

  it("accepts power generation technology, overview, and checksummed shard index", () => {
    const feature = {
      type: "Feature", id: "plant-1", geometry: { type: "Point", coordinates: [-119.5, 36.5] },
      properties: { id: "plant-1", country: "US", geographyId: "US-CA",
        technologies: ["solar"], capacityMw: 120,
        operatingCapacityMw: 120, plannedCapacityMw: 0, technologyMixMw: { solar: 120 },
        commissioningYear: 2024, retirementYear: null, targetYear: null, sourceIds: ["public-source"] },
    } as const;
    const parsedShard = generatorCountryShardSchema.parse({ type: "FeatureCollection", features: [feature] });
    expect(parsedShard.features[0].properties.technologies).toEqual(["solar"]);
    expect(parsedShard.features[0].properties.category).toBe("power_generation");
    expect(generatorOverviewSchema.parse({ type: "FeatureCollection", features: [{
      type: "Feature", id: "US-CA", geometry: { type: "Point", coordinates: [-119.5, 36.5] },
      properties: { geographyId: "US-CA", country: "US", count: 1, capacityMw: 120,
        operatingCapacityMw: 120, plannedCapacityMw: 0, technologyMixMw: { solar: 120 }, dominantTechnology: "solar" },
    }] }).features[0].properties.dominantTechnology).toBe("solar");
    expect(generatorIndexSchema.parse({ countries: { US: { bbox: [-120, 30, -110, 40], path: "generators/US.geojson", featureCount: 1, checksum: "a".repeat(64), bytes: 512, capacityMw: 120 } }, totals: { featureCount: 1, capacityMw: 120 } }).countries.US.bytes).toBe(512);
  });

  it("rejects invalid generator technologies, capacities, dates, and index paths", () => {
    const base = { type: "Feature", id: "plant-1", geometry: { type: "Point", coordinates: [1, 1] }, properties: {
      id: "plant-1", country: "US", geographyId: "US-CA", category: "power_generation", lifecycle: "operational",
      technologies: ["fusion"], capacityMw: -1, operatingCapacityMw: 0, plannedCapacityMw: 0,
      technologyMixMw: { solar: 0 }, commissioningYear: 1700, sourceIds: ["source"] } };
    expect(() => generatorCountryShardSchema.parse({ type: "FeatureCollection", features: [base] })).toThrow();
    expect(() => generatorIndexSchema.parse({ countries: { US: { bbox: [0, 0, 1, 1], path: "../US.geojson", featureCount: 1, checksum: "bad", bytes: -1, capacityMw: 1 } }, totals: { featureCount: 1, capacityMw: 1 } })).toThrow();
  });

  it("accepts the pipeline's camel-case power-generation asset contract", () => {
    const asset = assetPropertiesSchema.parse({
      id: "generator-de-solar-1-unit-a", name: "Example Solar Unit A",
      geographyId: "DE12", country: "DE", category: "power_generation", subtype: null,
      lifecycle: "operational", demandMw: null, technology: "solar",
      secondaryFuel: "battery storage", capacityMw: { low: 98, central: 100, high: 102 },
      dependableCapacityMw: { low: 8, central: 12, high: 16 },
      annualGenerationGwh: { low: 90, central: 105, high: 120 },
      commissioningYear: 2020, retirementYear: 2050,
      plantId: "generator-de-solar-1", unitId: "unit-a",
      locationPrecision: "exact", valueKind: "reported",
      sourceIds: ["official-generator-register"], sourceType: "research_verified", confidence: 90,
    });
    expect(asset.category).toBe("power_generation");
    expect(asset.subtype).toBeNull();
    expect(asset.technology).toBe("solar");
    expect(asset.annualGenerationGwh?.central).toBe(105);
  });

  it("enforces category-specific asset fields and generation provenance", () => {
    const base = {
      id: "asset-1", name: "Asset", geographyId: "DE12", country: "DE",
      lifecycle: "operational", demandMw: null, locationPrecision: "exact",
      valueKind: "reported", sourceIds: ["source-1"], confidence: 80,
    };
    expect(() => assetPropertiesSchema.parse({ ...base, category: "power_generation", subtype: null })).toThrow();
    expect(() => assetPropertiesSchema.parse({ ...base, category: "power_generation", subtype: "hyperscale", technology: "solar" })).toThrow();
    expect(() => assetPropertiesSchema.parse({ ...base, category: "power_generation", subtype: null, technology: "fusion" })).toThrow();
    expect(() => assetPropertiesSchema.parse({ ...base, category: "power_generation", subtype: null, technology: "solar", capacityMw: { low: -1, central: 2, high: 3 } })).toThrow();
    expect(() => assetPropertiesSchema.parse({ ...base, category: "power_generation", subtype: null, technology: "solar", commissioningYear: 2030, retirementYear: 2029 })).toThrow();
    expect(() => assetPropertiesSchema.parse({ ...base, category: "power_generation", subtype: null, technology: "solar", capacityMw: { low: 1, central: 2, high: 3 }, sourceIds: [] })).toThrow();
    expect(() => assetPropertiesSchema.parse({ ...base, category: "data_centre", subtype: "desalination" })).toThrow();
    expect(() => assetPropertiesSchema.parse({ ...base, category: "water_infrastructure", subtype: "hyperscale" })).toThrow();
    expect(() => assetPropertiesSchema.parse({ ...base, category: "data_centre", subtype: "hyperscale", technology: "solar" })).toThrow();
  });
});

describe("lazy snapshot layers", () => {
  afterEach(() => { clearSnapshotLayerCache(); vi.unstubAllGlobals(); });

  it("caches successful immutable paths and validates country shards", async () => {
    const payload = { type: "FeatureCollection", features: [] };
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });
    vi.stubGlobal("fetch", fetcher);
    const index = generatorIndexSchema.parse({ countries: { US: { bbox: [0, 0, 1, 1], path: "generators/US.geojson", featureCount: 0, checksum: "a".repeat(64), bytes: 2, capacityMw: 0 } }, totals: { featureCount: 0, capacityMw: 0 } });
    const [first, second] = await Promise.all([loadGeneratorCountry("snapshots/id", index, "US"), loadGeneratorCountry("snapshots/id", index, "US")]);
    expect(first.ok && first.data).toEqual(payload);
    expect(second.ok).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("evicts rejected and aborted requests and returns a recoverable layer error", async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new DOMException("stale", "AbortError"))
      .mockResolvedValueOnce({ ok: true, json: async () => ({ type: "FeatureCollection", features: [] }) });
    vi.stubGlobal("fetch", fetcher);
    const first = await loadGeneratorOverview("snapshots/id/generator-overview.geojson", { signal: new AbortController().signal });
    const second = await loadGeneratorOverview("snapshots/id/generator-overview.geojson");
    expect(first).toMatchObject({ ok: false, error: { recoverable: true, kind: "aborted" } });
    expect(second.ok).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("lets one observer abort without cancelling another observer's shared request", async () => {
    let resolveResponse!: (value: { ok: true; json: () => Promise<unknown> }) => void;
    const fetcher = vi.fn(() => new Promise((resolve) => { resolveResponse = resolve; }));
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    const aborted = loadGeneratorOverview("snapshots/id/generator-overview.geojson", { signal: controller.signal });
    const successful = loadGeneratorOverview("snapshots/id/generator-overview.geojson");
    controller.abort();
    resolveResponse({ ok: true, json: async () => ({ type: "FeatureCollection", features: [] }) });
    expect(await aborted).toMatchObject({ ok: false, error: { kind: "aborted" } });
    expect((await successful).ok).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("evicts a pending layer after its only observer aborts", async () => {
    const fetcher = vi.fn()
      .mockImplementationOnce((_path: string, options: { signal: AbortSignal }) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new DOMException("stale", "AbortError")), { once: true });
      }))
      .mockResolvedValueOnce({ ok: true, json: async () => ({ type: "FeatureCollection", features: [] }) });
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    const stale = loadGeneratorOverview("snapshots/id/generator-overview.geojson", { signal: controller.signal });
    controller.abort();
    expect(await stale).toMatchObject({ ok: false, error: { kind: "aborted" } });
    expect((await loadGeneratorOverview("snapshots/id/generator-overview.geojson")).ok).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("validates every lazy ADM1, energy, overview, and index response", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ malformed: true }) });
    vi.stubGlobal("fetch", fetcher);
    const results = await Promise.all([
      loadAdmin1("snapshots/id/admin1.geojson"),
      loadRegionalEnergy("snapshots/id/regional-energy.json"),
      loadGeneratorOverview("snapshots/id/generator-overview.geojson"),
      loadGeneratorIndex("snapshots/id/generators/index.json"),
    ]);
    expect(results.every((result) => !result.ok && result.error.kind === "invalid")).toBe(true);
  });
});

describe("global snapshot entities", () => {
  it("accepts a sourced water-infrastructure asset", () => {
    const asset = assetPropertiesSchema.parse({
      id: "asset-ae-desal-1",
      name: "Example plant",
      geographyId: "AE",
      category: "water_infrastructure",
      subtype: "desalination",
      lifecycle: "under_construction",
      demandMw: { low: 42, central: 50, high: 61 },
      locationPrecision: "city_centroid",
      valueKind: "estimated",
      sourceIds: ["source-1"],
      country: "AE",
      confidence: 72,
    });
    expect(asset.category).toBe("water_infrastructure");
  });

  it("preserves community facility provenance", () => {
    const asset = assetPropertiesSchema.parse({
      id: "osm-node-101",
      name: "Alpha DC",
      geographyId: "US",
      category: "data_centre",
      subtype: "other_data_centre",
      lifecycle: "operational",
      demandMw: null,
      locationPrecision: "exact",
      valueKind: "observed",
      sourceIds: ["openstreetmap-infrastructure"],
      sourceType: "community_mapped",
      sourceUrl: "https://www.openstreetmap.org/node/101",
      externalIds: { osm: "node/101" },
      lastObservedAt: "2026-06-27T12:00:00Z",
      operator: null,
      country: "US",
      confidence: 86,
    });

    expect(asset.sourceType).toBe("community_mapped");
    expect(asset.sourceUrl).toContain("openstreetmap.org/node/101");
  });

  it("preserves rich public facility fields without inventing power", () => {
    const asset = assetPropertiesSchema.parse({
      id: "osm-node-101", name: "Alpha DC", geographyId: "US-VA", country: "US",
      category: "data_centre", subtype: "other_data_centre", lifecycle: "operational",
      demandMw: null, locationPrecision: "exact", valueKind: "observed", sourceIds: ["osm"],
      sourceType: "community_mapped", confidence: 86, externalIds: { osm: "node/101", wikidata: "Q123" },
      owner: "Alpha Infrastructure", website: "https://alpha.example", facilityRef: "IAD-01",
      address: { street: "Compute Avenue", houseNumber: "101", city: "Ashburn", state: "Virginia", postcode: "20147", country: "US" },
      startDate: "2021", reportedPower: "48 MW",
    });

    expect(asset.address?.city).toBe("Ashburn");
    expect(asset.reportedPower).toBe("48 MW");
    expect(asset.demandMw).toBeNull();
  });

  it("loads the published countries and assets", async () => {
    const snapshot = await loadSnapshot();

    expect(snapshot.countries.features.length).toBeGreaterThan(190);
    expect(snapshot.admin1.features).toHaveLength(0);
    expect(snapshot.manifest.coverage.admin1Regions).toBeGreaterThan(3_000);
    expect(snapshot.assets.features.length).toBeGreaterThan(10);
    expect(snapshot.manifest.coverage.assets).toBe(snapshot.assets.features.length);
  });

  it("rejects a demand-contributing asset without a source", () => {
    expect(() =>
      assetPropertiesSchema.parse({
        id: "asset-us-dc-1",
        name: "Uncited campus",
        geographyId: "US",
        category: "data_centre",
        subtype: "hyperscale",
        lifecycle: "announced",
        demandMw: { low: 90, central: 100, high: 120 },
        locationPrecision: "region_centroid",
        valueKind: "estimated",
        sourceIds: [],
      }),
    ).toThrow();
  });

  it("labels countries as country-level peers", () => {
    const geography = geographyPropertiesSchema.parse({
      id: "AE",
      name: "United Arab Emirates",
      country: "AE",
      level: "country",
      parentId: null,
      scoreYear: 2030,
      scores: {
        infrastructureDemand: 72,
        siteAttractiveness: 68,
        systemRisk: 55,
      },
      scoresByYear: {
        "2030": { infrastructureDemand: 72, siteAttractiveness: 68, systemRisk: 55 },
      },
      categoryScoresByYear: {
        "2030": {
          combined: { infrastructureDemand: 72, siteAttractiveness: 68, systemRisk: 55 },
          data_centre: { infrastructureDemand: null, siteAttractiveness: null, systemRisk: null },
          water_infrastructure: { infrastructureDemand: 72, siteAttractiveness: 68, systemRisk: 55 },
        },
      },
      demandMwByYear: {
        "2030": {
          combined: { low: 42, central: 50, high: 61 },
          data_centre: null,
          water_infrastructure: { low: 42, central: 50, high: 61 },
        },
      },
      confidence: 80,
      coverage: 90,
      valueKind: "reported",
      updatedAt: "2026-06-27T04:12:00Z",
      contributions: [],
      contributionsByYear: { "2030": [] },
      sourceIds: ["source-1"],
      assetCount: 1,
      assetSummary: {
        total: 1,
        operational: 0,
        planned: 1,
        dataCentres: 0,
        waterInfrastructure: 1,
        officialVerified: 1,
        communityMapped: 0,
      },
    });
    expect(geography.assetSummary.planned).toBe(1);
    expect(geography.peerLevel).toBe("country");
  });
});
