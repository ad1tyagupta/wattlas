import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OpportunityRadar } from "@/components/opportunity-radar";
import type { SnapshotData } from "@/lib/snapshot/types";

const mockLoadRegionalEnergy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/snapshot/generators", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/snapshot/generators")>()),
  loadRegionalEnergy: mockLoadRegionalEnergy,
}));

afterEach(cleanup);

vi.mock("@/components/map/global-map", () => ({
  GlobalMap: ({ lens, onSelect, onSelectGenerator, onVisibleGeneratorsChange }: { lens: string; onSelect: (id: string) => void; onSelectGenerator: (feature: import("@/lib/snapshot/types").GeneratorFeature) => void; onVisibleGeneratorsChange: (ids: ReadonlySet<string>) => void }) => <div data-testid="global-map">Map lens: {lens}<button type="button" onClick={() => onSelect("osm-node-101")}>Select facility</button><button type="button" onClick={() => onSelect("IN-ASSAM")}>Select Assam</button><button type="button" onClick={() => onSelectGenerator(generator)}>Select generator</button><button type="button" onClick={() => onVisibleGeneratorsChange(new Set())}>Move away</button></div>,
}));

const generator = { type: "Feature", id: "generator-1", geometry: { type: "Point", coordinates: [8, 50] }, properties: { id: "generator-1", name: "Rhine Solar", category: "power_generation", country: "DE", geographyId: "DE-X", lifecycle: "operational", technologies: ["solar"], capacityMw: 80, operatingCapacityMw: 80, plannedCapacityMw: 0, technologyMixMw: { solar: 80 }, sourceIds: ["registry"] } } as import("@/lib/snapshot/types").GeneratorFeature;

const connectors: SnapshotData["manifest"]["connectors"] = [
  { id: "gisco", state: "current", checkedAt: "2026-06-27T04:12:00Z", lastSuccessAt: "2026-06-27T04:12:00Z", message: null },
  { id: "entsoe", state: "not_configured", checkedAt: "2026-06-27T04:12:00Z", lastSuccessAt: null, message: "Token missing" },
];

const snapshot: SnapshotData = {
  manifest: {
    snapshotId: "2026-06-27T04-12-00Z",
    generatedAt: "2026-06-27T04:12:00Z",
    modelVersion: "1.0.0",
    activeYears: [2026, 2027, 2028, 2029, 2030, 2031],
    artifacts: { countries: "countries.geojson", admin1: "admin1.geojson", regions: "regions.geojson", assets: "assets.geojson", evidence: "evidence.json" },
    coverage: { countries: 246, regions: 334, admin1Regions: 3229, countriesWithAdmin1: 197, assets: 14, dataCentres: 8, waterInfrastructure: 6 },
    boundaryDisclaimer: "UN boundary disclaimer",
    connectors,
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
  }] } as SnapshotData["admin1"],
  countries: {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        id: "DE71",
        geometry: { type: "Polygon", coordinates: [] },
        properties: {
          id: "DE71", name: "Darmstadt", country: "DE", scoreYear: 2030,
          level: "country", parentId: null, peerLevel: "country",
          scores: { infrastructureDemand: 78, siteAttractiveness: 54, systemRisk: 68 },
          scoresByYear: { "2030": { infrastructureDemand: 78, siteAttractiveness: 54, systemRisk: 68 } },
          categoryScoresByYear: {}, demandMwByYear: {}, assetCount: 0,
          assetSummary: { total: 0, operational: 0, planned: 0, dataCentres: 0, waterInfrastructure: 0, officialVerified: 0, communityMapped: 0 },
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
  }] } as SnapshotData["assets"],
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

  it("preserves a typed generator selection at the app boundary and shows an action", () => {
    render(<OpportunityRadar snapshot={snapshot} />);
    fireEvent.click(screen.getByRole("button", { name: "Select generator" }));
    expect(screen.getByRole("heading", { name: "Rhine Solar" })).toBeInTheDocument();
    expect(screen.getByText("80 MW")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Source record unavailable" })).toBeVisible();
  });

  it("clears a stale generator inspector when its layer, filter, or visible shard excludes it", () => {
    render(<OpportunityRadar snapshot={snapshot} />);
    const select = () => fireEvent.click(screen.getByRole("button", { name: "Select generator" }));
    select(); fireEvent.click(screen.getByRole("button", { name: "Power generators" }));
    expect(screen.queryByRole("heading", { name: "Rhine Solar" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Power generators" }));
    select(); fireEvent.click(screen.getByRole("button", { name: "Solar" }));
    expect(screen.queryByRole("heading", { name: "Rhine Solar" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Solar" }));
    select(); fireEvent.click(screen.getByRole("button", { name: "Move away" }));
    expect(screen.queryByRole("heading", { name: "Rhine Solar" })).not.toBeInTheDocument();
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
    for (const lifecycle of ["Under construction", "Planned", "Paused", "Cancelled or shelved", "Retired or decommissioned", "Unknown status"]) expect(screen.getByRole("button", { name: lifecycle })).toBeInTheDocument();
  });

  it("clears stale regional energy on snapshot path change and exposes a recoverable error", async () => {
    const forecast = Array.from({ length: 6 }, (_, index) => ({ geographyId: "DE71", year: 2026 + index, metrics: { demandGwh: { low: 90, central: 100, high: 110 }, localGenerationGwh: { low: 80, central: 90, high: 100 }, localGenerationGapGwh: { low: -10, central: 10, high: 30 }, netBalanceGwh: null, observedUnmetDemandGwh: null, installedCapacityMw: 50, dependableCapacityMw: { low: 30, central: 35, high: 40 }, peakDemandMw: { low: 20, central: 25, high: 30 } }, methodId: "m1", sourceIds: ["s1"], confidence: 70, coverage: 80, valueKind: "estimated", appliedIncrementIds: [], metricLineage: {} }));
    mockLoadRegionalEnergy.mockResolvedValueOnce({ ok: true, data: { DE71: forecast } }).mockResolvedValue({ ok: false, error: { kind: "network", message: "Network unavailable", recoverable: true, path: "snapshots/new/regional-energy.json" } });
    const first = { ...snapshot, manifest: { ...snapshot.manifest, snapshotId: "old", artifacts: { ...snapshot.manifest.artifacts, regionalEnergy: "snapshots/old/regional-energy.json" } } };
    const next = { ...snapshot, manifest: { ...snapshot.manifest, snapshotId: "new", artifacts: { ...snapshot.manifest.artifacts, regionalEnergy: "snapshots/new/regional-energy.json" } } };
    const { rerender } = render(<OpportunityRadar snapshot={first} />);
    fireEvent.click(screen.getByRole("button", { name: "Power Balance" }));
    expect((await screen.findAllByText("100 GWh")).length).toBeGreaterThan(0);
    rerender(<OpportunityRadar snapshot={next} />);
    await waitFor(() => expect(screen.queryAllByText("100 GWh")).toHaveLength(0));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load regional energy/i);
    expect(screen.getByRole("button", { name: /retry regional energy/i })).toBeInTheDocument();
  });
});
