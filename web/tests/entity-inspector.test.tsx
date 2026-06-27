import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EntityInspector } from "@/components/inspector/entity-inspector";
import type { AssetFeature, GeographyFeature } from "@/lib/snapshot/types";

describe("EntityInspector", () => {
  it("explains community facility provenance without inventing capacity", () => {
    const asset = {
      type: "Feature",
      id: "osm-node-101",
      geometry: { type: "Point", coordinates: [-77.1, 38.9] },
      properties: {
        id: "osm-node-101", name: "Alpha DC", operator: "Alpha Cloud", geographyId: "US", country: "US",
        category: "data_centre", subtype: "other_data_centre", lifecycle: "operational", demandMw: null,
        locationPrecision: "exact", valueKind: "observed", sourceIds: ["openstreetmap-infrastructure"],
        sourceType: "community_mapped", sourceUrl: "https://www.openstreetmap.org/node/101",
        externalIds: { osm: "node/101" }, lastObservedAt: "2026-06-27T12:00:00Z", confidence: 86,
      },
    } as AssetFeature;

    render(<EntityInspector geography={null} asset={asset} lens="infrastructureDemand" year={2030} onOpenEvidence={vi.fn()} onAddComparison={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Alpha DC" })).toBeInTheDocument();
    expect(screen.getByText("Community mapped")).toBeInTheDocument();
    expect(screen.getByText("Operational")).toBeInTheDocument();
    expect(screen.getByText("Not publicly available")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open source record" })).toHaveAttribute("href", "https://www.openstreetmap.org/node/101");
  });

  it("shows country facility coverage splits", () => {
    const geography = {
      type: "Feature", id: "US", geometry: { type: "Polygon", coordinates: [] },
      properties: {
        id: "US", name: "United States", country: "US", level: "country", parentId: null, peerLevel: "country",
        scoreYear: 2030, scores: { infrastructureDemand: 70, siteAttractiveness: 60, systemRisk: 50 },
        scoresByYear: { "2030": { infrastructureDemand: 70, siteAttractiveness: 60, systemRisk: 50 } },
        categoryScoresByYear: {}, demandMwByYear: {}, confidence: 75, coverage: 90, valueKind: "estimated",
        updatedAt: "2026-06-27T12:00:00Z", contributions: [], contributionsByYear: { "2030": [] }, sourceIds: [],
        assetCount: 512, assetSummary: { total: 512, operational: 480, planned: 32, dataCentres: 500, waterInfrastructure: 12, officialVerified: 20, communityMapped: 492 },
      },
    } as GeographyFeature;

    render(<EntityInspector geography={geography} asset={null} lens="infrastructureDemand" year={2030} onOpenEvidence={vi.fn()} onAddComparison={vi.fn()} />);

    expect(screen.getByText("512 facilities")).toBeInTheDocument();
    expect(screen.getByText("480 operational")).toBeInTheDocument();
    expect(screen.getByText("32 planned")).toBeInTheDocument();
    expect(screen.getByText("492 community mapped")).toBeInTheDocument();
  });
});
