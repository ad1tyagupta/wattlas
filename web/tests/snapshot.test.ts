import { describe, expect, it } from "vitest";

import {
  assetPropertiesSchema,
  geographyPropertiesSchema,
  manifestSchema,
} from "@/lib/snapshot/schema";
import { loadSnapshot } from "@/lib/snapshot/load";

const validManifest = {
  snapshotId: "2026-06-27T04-12-00Z",
  generatedAt: "2026-06-27T04:12:00Z",
  modelVersion: "1.0.0",
  activeYears: [2026, 2027, 2028, 2029, 2030, 2031],
  artifacts: {
    countries: "countries.geojson",
    regions: "regions.geojson",
    assets: "assets.geojson",
    evidence: "evidence.json",
  },
  coverage: {
    countries: 246,
    regions: 334,
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

  it("loads the published countries and assets", async () => {
    const snapshot = await loadSnapshot();

    expect(snapshot.countries.features.length).toBeGreaterThan(190);
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
    });
    expect(geography.peerLevel).toBe("country");
  });
});
