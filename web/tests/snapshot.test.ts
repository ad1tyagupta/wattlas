import { describe, expect, it } from "vitest";

import { manifestSchema } from "@/lib/snapshot/schema";

const validManifest = {
  snapshotId: "2026-06-27T04-12-00Z",
  generatedAt: "2026-06-27T04:12:00Z",
  modelVersion: "1.0.0",
  activeYears: [2026, 2027, 2028, 2029, 2030, 2031],
  artifacts: {
    regions: "regions.geojson",
    projects: "projects.geojson",
    evidence: "evidence.json",
  },
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
