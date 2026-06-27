import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OpportunityRadar } from "@/components/opportunity-radar";

vi.mock("@/components/map/global-map", () => ({
  GlobalMap: () => <div data-testid="global-map">Map</div>,
}));

const snapshot = {
  manifest: {
    snapshotId: "2026-06-27T04-12-00Z",
    generatedAt: "2026-06-27T04:12:00Z",
    modelVersion: "1.0.0",
    activeYears: [2026, 2027, 2028, 2029, 2030, 2031],
    artifacts: { countries: "countries.geojson", regions: "regions.geojson", assets: "assets.geojson", evidence: "evidence.json" },
    coverage: { countries: 246, regions: 334, assets: 14, dataCentres: 8, waterInfrastructure: 6 },
    boundaryDisclaimer: "UN boundary disclaimer",
    connectors: [
      { id: "gisco", state: "current", checkedAt: "2026-06-27T04:12:00Z", lastSuccessAt: "2026-06-27T04:12:00Z", message: null },
      { id: "entsoe", state: "not_configured", checkedAt: "2026-06-27T04:12:00Z", lastSuccessAt: null, message: "Token missing" },
    ],
  },
  countries: {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        id: "DE71",
        geometry: { type: "Polygon", coordinates: [] },
        properties: {
          id: "DE71", name: "Darmstadt", country: "DE", scoreYear: 2030,
          scores: { infrastructureDemand: 78, siteAttractiveness: 54, systemRisk: 68 },
          scoresByYear: { "2030": { infrastructureDemand: 78, siteAttractiveness: 54, systemRisk: 68 } },
          confidence: 72, coverage: 100, valueKind: "estimated", updatedAt: "2026-06-27T04:12:00Z",
          contributions: [], contributionsByYear: { "2030": [] }, sourceIds: ["source-1"], population: 4_100_000, clusterId: "frankfurt",
        },
      },
    ],
  },
  regions: { type: "FeatureCollection", features: [] },
  assets: { type: "FeatureCollection", features: [] },
  evidence: { sources: [], claims: [] },
};

describe("OpportunityRadar", () => {
  it("renders daily freshness, lenses, year, and source truth", () => {
    render(<OpportunityRadar snapshot={snapshot} />);

    expect(screen.getByText("WATTLAS")).toBeInTheDocument();
    expect(screen.getByText(/Daily refreshed/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Infrastructure Demand" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Site Attractiveness" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "System Risk" })).toBeInTheDocument();
    expect(screen.getAllByText("2030").length).toBeGreaterThan(0);
    expect(screen.queryByText(/^LIVE$/)).not.toBeInTheDocument();
  });
});
