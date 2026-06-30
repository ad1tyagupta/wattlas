import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OpportunityRadar } from "@/components/opportunity-radar";
import type { SnapshotData } from "@/lib/snapshot/types";

afterEach(cleanup);

vi.mock("@/components/map/global-map", () => ({
  GlobalMap: ({ lens, onSelect }: { lens: string; onSelect: (id: string) => void }) => <div data-testid="global-map">Map lens: {lens}<button type="button" onClick={() => onSelect("osm-node-101")}>Select facility</button><button type="button" onClick={() => onSelect("IN-ASSAM")}>Select Assam</button></div>,
}));

const snapshot = {
  manifest: {
    snapshotId: "2026-06-27T04-12-00Z",
    generatedAt: "2026-06-27T04:12:00Z",
    modelVersion: "1.0.0",
    activeYears: [2026, 2027, 2028, 2029, 2030, 2031],
    artifacts: { countries: "countries.geojson", admin1: "admin1.geojson", regions: "regions.geojson", assets: "assets.geojson", evidence: "evidence.json" },
    coverage: { countries: 246, regions: 334, admin1Regions: 3229, countriesWithAdmin1: 197, assets: 14, dataCentres: 8, waterInfrastructure: 6 },
    boundaryDisclaimer: "UN boundary disclaimer",
    connectors: [
      { id: "gisco", state: "current" as const, checkedAt: "2026-06-27T04:12:00Z", lastSuccessAt: "2026-06-27T04:12:00Z", message: null },
      { id: "entsoe", state: "not_configured" as const, checkedAt: "2026-06-27T04:12:00Z", lastSuccessAt: null, message: "Token missing" },
    ],
  },
  admin1: { type: "FeatureCollection", features: [{
    type: "Feature", id: "IN-ASSAM", geometry: { type: "Polygon", coordinates: [] },
    properties: {
      id: "IN-ASSAM", name: "Assam", country: "IN", level: "admin_1", parentId: "IN", peerLevel: "admin_1",
      scoreYear: 2030, scores: { infrastructureDemand: null, siteAttractiveness: null, systemRisk: null },
      scoresByYear: { "2030": { infrastructureDemand: null, siteAttractiveness: null, systemRisk: null } },
      categoryScoresByYear: {}, demandMwByYear: {}, confidence: 0, coverage: 0, valueKind: "unavailable", updatedAt: "2026-06-28T00:00:00Z",
      contributions: [], contributionsByYear: { "2030": [] }, sourceIds: [], assetCount: 1,
      assetSummary: { total: 1, operational: 1, planned: 0, dataCentres: 1, waterInfrastructure: 0, officialVerified: 0, communityMapped: 1 },
    },
  }] },
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
  assets: { type: "FeatureCollection", features: [{
    type: "Feature", id: "osm-node-101", geometry: { type: "Point", coordinates: [-77.1, 38.9] },
    properties: {
      id: "osm-node-101", name: "Alpha DC", operator: "Alpha Cloud", geographyId: "US", country: "US",
      category: "data_centre", subtype: "other_data_centre", lifecycle: "operational", demandMw: null,
      locationPrecision: "exact", valueKind: "observed", sourceIds: ["openstreetmap-infrastructure"],
      sourceType: "community_mapped", sourceUrl: "https://www.openstreetmap.org/node/101", externalIds: { osm: "node/101" },
      lastObservedAt: "2026-06-27T12:00:00Z", confidence: 86,
    },
  }] },
  evidence: { sources: [], claims: [] },
} as unknown as SnapshotData;

describe("OpportunityRadar", () => {
  it("renders daily freshness, lenses, year, and source truth", () => {
    render(<OpportunityRadar snapshot={snapshot} />);

    expect(screen.getByText("WATTLAS")).toBeInTheDocument();
    expect(screen.getByText(/Daily refreshed/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Infrastructure Demand" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Site Attractiveness" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "System Risk" })).toBeInTheDocument();
    const powerBalance = screen.getByRole("button", { name: "Power Balance" });
    expect(powerBalance).toHaveTextContent("04");
    fireEvent.click(powerBalance);
    expect(screen.getByTestId("global-map")).toHaveTextContent("powerBalance");
    expect(screen.getByText("Comfortable margin")).toBeInTheDocument();
    expect(screen.getByText("Severe pressure")).toBeInTheDocument();
    expect(screen.getAllByText("2030").length).toBeGreaterThan(0);
    expect(screen.queryByText(/^LIVE$/)).not.toBeInTheDocument();
  });

  it("selects and inspects an individual facility", () => {
    render(<OpportunityRadar snapshot={snapshot} />);

    fireEvent.click(screen.getByRole("button", { name: "Select facility" }));

    expect(screen.getByRole("heading", { name: "Alpha DC" })).toBeInTheDocument();
    expect(screen.getByText("Community mapped")).toBeInTheDocument();
  });

  it("selects and inspects a global first-level region", () => {
    render(<OpportunityRadar snapshot={snapshot} />);

    fireEvent.click(screen.getByRole("button", { name: "Select Assam" }));

    expect(screen.getByRole("heading", { name: "Assam" })).toBeInTheDocument();
    expect(screen.getByText("1 facilities")).toBeInTheDocument();
  });

  it("offers independent infrastructure layers and accessible generator filters", () => {
    render(<OpportunityRadar snapshot={snapshot} />);
    for (const name of ["Data centres", "Water infrastructure", "Power generators"]) {
      const toggle = screen.getByRole("button", { name });
      expect(toggle).toHaveAttribute("aria-pressed", "true");
      fireEvent.click(toggle);
      expect(toggle).toHaveAttribute("aria-pressed", "false");
    }
    fireEvent.click(screen.getByRole("button", { name: "Power generators" }));
    const solar = screen.getByRole("button", { name: "Solar" });
    expect(solar).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(solar);
    expect(solar).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Operational" })).toBeInTheDocument();
  });
});
