import { afterEach, describe, expect, it, vi } from "vitest";

import {
  assetPropertiesSchema,
  generatorCountryShardSchema,
  generatorIndexSchema,
  generatorOverviewSchema,
  geographyPropertiesSchema,
  manifestSchema,
  regionalEnergySchema,
  scoreContributionSchema,
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
    countries: "snapshots/2026-06-27T04-12-00Z/countries.geojson",
    admin1: "snapshots/2026-06-27T04-12-00Z/admin1.geojson",
    regions: "snapshots/2026-06-27T04-12-00Z/regions.geojson",
    assets: "snapshots/2026-06-27T04-12-00Z/assets.geojson",
    evidence: "snapshots/2026-06-27T04-12-00Z/evidence.json",
    regionalEnergy: "snapshots/2026-06-27T04-12-00Z/regional-energy.json",
    generatorOverview: "snapshots/2026-06-27T04-12-00Z/generator-overview.geojson",
    generatorIndex: "snapshots/2026-06-27T04-12-00Z/generators/index.json",
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

function jsonResponse(payload: unknown, contentType = "application/json; charset=utf-8"): Response {
  return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": contentType } });
}

async function sha256(body: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

describe("snapshot manifest", () => {
  it("accepts the six-year snapshot contract", () => {
    expect(manifestSchema.parse(validManifest).activeYears).toHaveLength(6);
  });

  it("keeps ADM1, regional energy, and generator layers out of the server payload", () => {
    const manifest = manifestSchema.parse(validManifest);
    expect(serverSnapshotArtifactPaths(manifest)).toEqual({
      countries: "snapshots/2026-06-27T04-12-00Z/countries.geojson",
      regions: "snapshots/2026-06-27T04-12-00Z/regions.geojson",
      assets: "snapshots/2026-06-27T04-12-00Z/assets.geojson",
      evidence: "snapshots/2026-06-27T04-12-00Z/evidence.json",
    });
  });

  it("rejects server artifact paths that could read outside the exact snapshot", () => {
    for (const countries of ["../../secret.json", "/tmp/secret.json", "snapshots/id/../secret.json", "snapshots\\id\\countries.geojson", "snapshots/id/countries.geojson?x=1"]) {
      const manifest = manifestSchema.parse({ ...validManifest, artifacts: { ...validManifest.artifacts, countries } });
      expect(() => serverSnapshotArtifactPaths(manifest)).toThrow();
    }
    const unsafeId = manifestSchema.parse({ ...validManifest, snapshotId: ".." });
    expect(() => serverSnapshotArtifactPaths(unsafeId)).toThrow();
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

  it("preserves canonical power coverage and refresh quality metadata", () => {
    const parsed = manifestSchema.parse({
      ...validManifest,
      coverage: { ...validManifest.coverage, canonicalPowerUnits: 120, powerSourceRecordsBySource: { gem_power: 80, osm_power: 40 } },
      quality: { countryDemandReconciled: true, generatorArtifactsReconciled: true, populationBuildFingerprint: null, demandWeightsBuildFingerprint: "b".repeat(64) },
    });
    expect(parsed.coverage.canonicalPowerUnits).toBe(120);
    expect(parsed.coverage.powerSourceRecordsBySource?.gem_power).toBe(80);
    expect(parsed.quality?.generatorArtifactsReconciled).toBe(true);
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

  it("requires coherent, versioned score contributions", () => {
    const valid = {
      id: "capacity_margin", label: "Capacity margin", rawValue: 22, unit: "%",
      points: 18, maxPoints: 25, valueKind: "estimated", sourceIds: ["grid-source"],
      normalization: "Fixed bands", methodVersion: "power-balance-v1",
    };
    expect(scoreContributionSchema.parse(valid).methodVersion).toBe("power-balance-v1");
    expect(() => scoreContributionSchema.parse({ ...valid, methodVersion: undefined })).toThrow();
    expect(() => scoreContributionSchema.parse({ ...valid, points: 26 })).toThrow();
    expect(() => scoreContributionSchema.parse({ ...valid, valueKind: "unavailable" })).toThrow();
    expect(scoreContributionSchema.parse({ ...valid, rawValue: null, points: null, valueKind: "unavailable", sourceIds: [] }).points).toBeNull();
    expect(() => scoreContributionSchema.parse({ ...valid, sourceIds: [""] })).toThrow();
  });

  it("rejects net balance without both local supply metrics", () => {
    const rows = Array.from({ length: 6 }, (_, i) => ({ ...forecast, year: 2026 + i,
      metrics: { ...forecast.metrics, localGenerationGwh: null, localGenerationGapGwh: null, netBalanceGwh: range },
    }));
    expect(() => regionalEnergySchema.parse({ "US-CA": rows })).toThrow();
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
    const body = JSON.stringify(payload);
    const fetcher = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetcher);
    const index = generatorIndexSchema.parse({ countries: { US: { bbox: [0, 0, 1, 1], path: "generators/US.geojson", featureCount: 0, checksum: await sha256(body), bytes: new TextEncoder().encode(body).byteLength, capacityMw: 0 } }, totals: { featureCount: 0, capacityMw: 0 } });
    const [first, second] = await Promise.all([loadGeneratorCountry("snapshots/id", index, "US"), loadGeneratorCountry("snapshots/id", index, "US")]);
    expect(first.ok && first.data).toEqual(payload);
    expect(second.ok).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("evicts rejected and aborted requests and returns a recoverable layer error", async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new DOMException("stale", "AbortError"))
      .mockResolvedValueOnce(jsonResponse({ type: "FeatureCollection", features: [] }));
    vi.stubGlobal("fetch", fetcher);
    const first = await loadGeneratorOverview("snapshots/id/generator-overview.geojson", { signal: new AbortController().signal });
    const second = await loadGeneratorOverview("snapshots/id/generator-overview.geojson");
    expect(first).toMatchObject({ ok: false, error: { recoverable: true, kind: "aborted" } });
    expect(second.ok).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("lets one observer abort without cancelling another observer's shared request", async () => {
    let resolveResponse!: (value: Response) => void;
    const fetcher = vi.fn(() => new Promise((resolve) => { resolveResponse = resolve; }));
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    const aborted = loadGeneratorOverview("snapshots/id/generator-overview.geojson", { signal: controller.signal });
    const successful = loadGeneratorOverview("snapshots/id/generator-overview.geojson");
    controller.abort();
    resolveResponse(jsonResponse({ type: "FeatureCollection", features: [] }));
    expect(await aborted).toMatchObject({ ok: false, error: { kind: "aborted" } });
    expect((await successful).ok).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("evicts a pending layer after its only observer aborts", async () => {
    const fetcher = vi.fn()
      .mockImplementationOnce((_path: string, options: { signal: AbortSignal }) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new DOMException("stale", "AbortError")), { once: true });
      }))
      .mockResolvedValueOnce(jsonResponse({ type: "FeatureCollection", features: [] }));
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    const stale = loadGeneratorOverview("snapshots/id/generator-overview.geojson", { signal: controller.signal });
    controller.abort();
    expect(await stale).toMatchObject({ ok: false, error: { kind: "aborted" } });
    expect((await loadGeneratorOverview("snapshots/id/generator-overview.geojson")).ok).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("validates every lazy ADM1, energy, overview, and index response", async () => {
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ malformed: true })));
    vi.stubGlobal("fetch", fetcher);
    const results = await Promise.all([
      loadAdmin1("snapshots/id/admin1.geojson"),
      loadRegionalEnergy("snapshots/id/regional-energy.json"),
      loadGeneratorOverview("snapshots/id/generator-overview.geojson"),
      loadGeneratorIndex("snapshots/id/generators/index.json"),
    ]);
    expect(results.every((result) => !result.ok && result.error.kind === "invalid")).toBe(true);
  });

  it("migrates only explicitly opted-in legacy 2.1 ADM1 contributions", async () => {
    const contribution = {
      id: "projected_load", label: "Projected load", rawValue: 88, unit: "index",
      points: 52.8, maxPoints: 60, valueKind: "estimated", sourceIds: ["source-1"], normalization: "Wattlas 2.1 fixed threshold",
    };
    const payload = { type: "FeatureCollection", features: [{
      type: "Feature", id: "US-CA", geometry: { type: "Polygon", coordinates: [] }, properties: {
        id: "US-CA", name: "California", country: "US", level: "admin_1", parentId: "US", peerLevel: "admin_1",
        scoreYear: 2030, scores: { infrastructureDemand: 60, siteAttractiveness: 50, systemRisk: 40 },
        scoresByYear: { "2030": { infrastructureDemand: 60, siteAttractiveness: 50, systemRisk: 40 } },
        categoryScoresByYear: {}, demandMwByYear: {}, confidence: 70, coverage: 80, valueKind: "estimated",
        updatedAt: "2026-06-28T05:11:05Z", contributions: [contribution], contributionsByYear: { "2030": [contribution] },
        sourceIds: ["source-1"], assetCount: 0,
        assetSummary: { total: 0, operational: 0, planned: 0, dataCentres: 0, waterInfrastructure: 0, officialVerified: 0, communityMapped: 0 },
      },
    }] };
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(payload)));
    vi.stubGlobal("fetch", fetcher);
    expect(await loadAdmin1("snapshots/legacy-id/admin1.geojson", { modelVersion: "2.1.0" })).toMatchObject({ ok: false, error: { kind: "invalid" } });
    const migrated = await loadAdmin1("snapshots/legacy-id/admin1.geojson", { modelVersion: "2.1.0", legacyContributions: true });
    expect(migrated.ok && migrated.data.features[0].properties.contributions[0].methodVersion).toBe("legacy-2.1.0");
    expect(await loadAdmin1("snapshots/new-id/admin1.geojson", { modelVersion: "3.0.0", legacyContributions: true })).toMatchObject({ ok: false, error: { kind: "invalid" } });
  });

  it("rejects tampered shard bytes before schema parsing", async () => {
    const payload = { type: "FeatureCollection", features: [] };
    const expected = JSON.stringify(payload);
    const tampered = `${expected} `;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(tampered, { headers: { "content-type": "application/geo+json" } })));
    const index = generatorIndexSchema.parse({ countries: { US: { bbox: [0, 0, 1, 1], path: "generators/US.geojson", featureCount: 0, checksum: await sha256(expected), bytes: new TextEncoder().encode(expected).byteLength, capacityMw: 0 } }, totals: { featureCount: 0, capacityMw: 0 } });
    expect(await loadGeneratorCountry("snapshots/safe-id", index, "US")).toMatchObject({ ok: false, error: { kind: "invalid" } });
  });

  it("rejects a shard whose decoded feature count disagrees with its index", async () => {
    const payload = { type: "FeatureCollection", features: [] };
    const body = JSON.stringify(payload);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(payload)));
    const index = generatorIndexSchema.parse({ countries: { US: { bbox: [0, 0, 1, 1], path: "generators/US.geojson", featureCount: 1, checksum: await sha256(body), bytes: new TextEncoder().encode(body).byteLength, capacityMw: 0 } }, totals: { featureCount: 1, capacityMw: 0 } });
    expect(await loadGeneratorCountry("snapshots/safe-id", index, "US")).toMatchObject({ ok: false, error: { kind: "invalid" } });
  });

  it("isolates cache entries by loader schema even for the same path", async () => {
    const payload = {};
    const fetcher = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetcher);
    const path = "snapshots/safe-id/shared.json";
    expect((await loadRegionalEnergy(path)).ok).toBe(true);
    expect((await loadGeneratorIndex(path)).ok).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("classifies invalid MIME and JSON decoding separately from transport errors", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response("{}", { headers: { "content-type": "text/html" } }))
      .mockResolvedValueOnce(new Response("{", { headers: { "content-type": "application/json" } }))
      .mockRejectedValueOnce(new TypeError("offline"));
    vi.stubGlobal("fetch", fetcher);
    expect(await loadGeneratorOverview("snapshots/safe-id/a.geojson")).toMatchObject({ ok: false, error: { kind: "invalid" } });
    expect(await loadGeneratorOverview("snapshots/safe-id/b.geojson")).toMatchObject({ ok: false, error: { kind: "invalid" } });
    expect(await loadGeneratorOverview("snapshots/safe-id/c.geojson")).toMatchObject({ ok: false, error: { kind: "network" } });
  });

  it("classifies HTTP status separately and rejects advertised oversized layers", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response("unavailable", { status: 503, headers: { "content-type": "text/plain" } }))
      .mockResolvedValueOnce(new Response("{}", { headers: { "content-type": "application/json", "content-length": String(3 * 1024 * 1024) } }));
    vi.stubGlobal("fetch", fetcher);
    expect(await loadGeneratorIndex("snapshots/safe-id/status.json")).toMatchObject({ ok: false, error: { kind: "http" } });
    expect(await loadGeneratorIndex("snapshots/safe-id/large.json")).toMatchObject({ ok: false, error: { kind: "invalid" } });
  });

  it("bounds immutable cache growth with least-recently-used eviction", async () => {
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ type: "FeatureCollection", features: [] })));
    vi.stubGlobal("fetch", fetcher);
    for (let index = 0; index < 33; index += 1) {
      expect((await loadGeneratorOverview(`snapshots/safe-id/overview-${index}.geojson`)).ok).toBe(true);
    }
    expect((await loadGeneratorOverview("snapshots/safe-id/overview-0.geojson")).ok).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(34);
  });

  it("does not abort any of 33 concurrent actively observed layers under LRU pressure", async () => {
    const resolvers: Array<(response: Response) => void> = [];
    const signals: AbortSignal[] = [];
    const fetcher = vi.fn((_url: string, options: { signal: AbortSignal }) => {
      signals.push(options.signal);
      return new Promise<Response>((resolve) => resolvers.push(resolve));
    });
    vi.stubGlobal("fetch", fetcher);
    const pending = Array.from({ length: 33 }, (_, index) => loadGeneratorOverview(`snapshots/concurrent-id/overview-${index}.geojson`));
    expect(signals).toHaveLength(33);
    expect(signals.every((signal) => !signal.aborted)).toBe(true);
    for (const resolve of resolvers) resolve(jsonResponse({ type: "FeatureCollection", features: [] }));
    const results = await Promise.all(pending);
    expect(results.every((result) => result.ok)).toBe(true);
    expect(signals.every((signal) => !signal.aborted)).toBe(true);
  });

  it("rejects oversized indexed shards before fetch", async () => {
    const index = generatorIndexSchema.parse({ countries: { US: { bbox: [0, 0, 1, 1], path: "generators/US.geojson", featureCount: 250_001, checksum: "a".repeat(64), bytes: 32 * 1024 * 1024 + 1, capacityMw: 0 } }, totals: { featureCount: 250_001, capacityMw: 0 } });
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect(await loadGeneratorCountry("snapshots/safe-id", index, "US")).toMatchObject({ ok: false, error: { kind: "invalid" } });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects unsafe snapshot roots before fetching", async () => {
    const index = generatorIndexSchema.parse({ countries: { US: { bbox: [0, 0, 1, 1], path: "generators/US.geojson", featureCount: 0, checksum: "a".repeat(64), bytes: 2, capacityMw: 0 } }, totals: { featureCount: 0, capacityMw: 0 } });
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    for (const root of ["snapshots/../secret", "snapshots/id?x=1", "snapshots/id#x", "snapshots\\id", "/snapshots/id", "snapshots/id/extra"]) {
      expect(await loadGeneratorCountry(root, index, "US")).toMatchObject({ ok: false, error: { kind: "invalid" } });
    }
    expect(fetcher).not.toHaveBeenCalled();
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
