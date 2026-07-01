import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EntityInspector } from "@/components/inspector/entity-inspector";
import type { AssetFeature, GeneratorFeature, GeographyFeature, GeneratorOverviewCollection, RegionalEnergyForecast } from "@/lib/snapshot/types";

afterEach(cleanup);

const energy = (year: number, netBalanceGwh: RegionalEnergyForecast["metrics"]["netBalanceGwh"] = null, observedUnmetDemandGwh: number | null = null): RegionalEnergyForecast => ({
  geographyId: "US-CA", year,
  metrics: {
    demandGwh: { low: 950, central: 1000, high: 1050 }, localGenerationGwh: { low: 780, central: 800, high: 820 },
    localGenerationGapGwh: { low: 130, central: 200, high: 270 }, netBalanceGwh, observedUnmetDemandGwh,
    installedCapacityMw: 300, dependableCapacityMw: { low: 210, central: 225, high: 240 }, peakDemandMw: { low: 150, central: 160, high: 170 },
  },
  powerBalance: { score: 58, coverage: 80, status: "rankable", contributions: [{ id: "gap", label: "Local supply coverage", rawValue: 80, unit: "%", points: 20, maxPoints: 25, valueKind: "estimated", sourceIds: ["energy-source"], normalization: "80% supply coverage", methodVersion: "power-balance-v1" }] },
  methodId: "regional-power-balance-v1", sourceIds: ["energy-source"], confidence: 72, coverage: 80, valueKind: "estimated", appliedIncrementIds: [],
  metricLineage: { demandGwh: { sourceIds: ["energy-source"], methodId: "demand-v1", valueKind: "estimated" } },
});

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
        owner: "Alpha Infrastructure", website: "https://alpha.example/dc", facilityRef: "IAD-01",
        address: { street: "Compute Avenue", houseNumber: "101", city: "Ashburn", state: "Virginia", postcode: "20147", country: "US" },
        startDate: "2021", reportedPower: "48 MW",
      },
    } as AssetFeature;

    render(<EntityInspector geography={null} asset={asset} lens="infrastructureDemand" year={2030} onOpenEvidence={vi.fn()} onAddComparison={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Alpha DC" })).toBeInTheDocument();
    expect(screen.getByText("Community mapped")).toBeInTheDocument();
    expect(screen.getByText("Operational")).toBeInTheDocument();
    expect(screen.getByText("Not publicly available")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open source record" })).toHaveAttribute("href", "https://www.openstreetmap.org/node/101");
    expect(screen.getByRole("heading", { name: "Identity" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Location" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Operations" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Energy" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sources" })).toBeInTheDocument();
    expect(screen.getByText("Alpha Infrastructure")).toBeInTheDocument();
    expect(screen.getByText(/101 Compute Avenue/)).toBeInTheDocument();
    expect(screen.getByText("48 MW")).toBeInTheDocument();
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

  it("shows regional power balance facts, sources, arithmetic, and honest nullable metrics", () => {
    const geography = {
      type: "Feature", id: "US-CA", geometry: { type: "Polygon", coordinates: [] }, properties: {
        id: "US-CA", name: "California", country: "US", level: "admin_1", parentId: "US", peerLevel: "admin_1", scoreYear: 2030,
        scores: { infrastructureDemand: 70, siteAttractiveness: 60, systemRisk: 50, powerBalance: 58 }, scoresByYear: { "2030": { infrastructureDemand: 70, siteAttractiveness: 60, systemRisk: 50, powerBalance: 58 } },
        categoryScoresByYear: {}, demandMwByYear: { "2030": { data_centre: { low: 20, central: 25, high: 30 }, water_infrastructure: { low: 4, central: 5, high: 6 }, combined: { low: 24, central: 30, high: 36 } } },
        confidence: 72, coverage: 80, valueKind: "estimated", updatedAt: "2026-06-28T00:00:00Z", contributions: [], contributionsByYear: {}, sourceIds: ["energy-source"], assetCount: 0,
        assetSummary: { total: 0, operational: 0, planned: 0, dataCentres: 0, waterInfrastructure: 0, officialVerified: 0, communityMapped: 0 },
        population: 39_000_000, populationSourceYear: 2024, populationYear: 2030, populationValueKind: "estimated",
      },
    } as GeographyFeature;
    const overview = { type: "FeatureCollection", features: [{ type: "Feature", id: "US-CA", geometry: { type: "Point", coordinates: [-120, 37] }, properties: { geographyId: "US-CA", country: "US", count: 5, capacityMw: 300, operatingCapacityMw: 250, plannedCapacityMw: 50, technologyMixMw: { solar: 180, gas: 120 }, dominantTechnology: "solar", lifecycleCounts: { operational: 3, under_construction: 1, announced: 1 } } }] } as GeneratorOverviewCollection;
    render(<EntityInspector geography={geography} asset={null} lens="powerBalance" year={2030} regionalEnergy={Array.from({ length: 6 }, (_, i) => energy(2026 + i))} generatorOverview={overview} evidence={{ sources: [{ id: "energy-source", name: "Public Energy Office", tier: "A", url: "https://energy.example/source", publishedAt: "2025-01-01" }], claims: [] }} onOpenEvidence={vi.fn()} onAddComparison={vi.fn()} />);

    expect(screen.getByText(/39 million/)).toBeInTheDocument();
    expect(screen.getByText(/source year 2024/i)).toBeInTheDocument();
    expect(screen.getByText(/forecast growth/i)).toBeInTheDocument();
    expect(screen.getByText(/1,000 GWh/)).toBeInTheDocument();
    expect(screen.getByText(/160 MW/)).toBeInTheDocument();
    expect(screen.getByText(/800 GWh/)).toBeInTheDocument();
    expect(screen.getByText(/225 MW/)).toBeInTheDocument();
    expect(screen.getByText(/local generation gap/i)).toBeInTheDocument();
    expect(screen.queryByText(/deficit/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/net balance/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/observed unmet/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Solar 60%/)).toBeInTheDocument();
    expect(screen.getByText(/3 operational/)).toBeInTheDocument();
    expect(screen.getByText(/Data-centre forward demand/i)).toBeInTheDocument();
    expect(screen.getByText(/Water forward demand/i)).toBeInTheDocument();
    expect(screen.getByText("20/25 points")).toBeInTheDocument();
    expect(screen.getByText("80 %")).toBeInTheDocument();
    expect(screen.getByText("80% supply coverage")).toBeInTheDocument();
    expect(screen.getByText(/Estimated · power-balance-v1/)).toBeInTheDocument();
    expect(screen.getByText(/Sources: energy-source/)).toBeInTheDocument();
    expect(screen.getByText(/20 of 25 available points/i)).toBeInTheDocument();
    expect(screen.getByText(/Rankable at 80% coverage/i)).toBeInTheDocument();
    expect(screen.getAllByText(/80% coverage/i)).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Public Energy Office" })).toHaveAttribute("href", "https://energy.example/source");
    expect(screen.getByText(/regional-power-balance-v1/i)).toBeInTheDocument();
  });

  it("shows net balance and observed unmet demand only when reported", () => {
    const geography = { type: "Feature", id: "US-CA", geometry: { type: "Polygon", coordinates: [] }, properties: { id: "US-CA", name: "California", country: "US", level: "admin_1", parentId: "US", peerLevel: "admin_1", scoreYear: 2030, scores: { infrastructureDemand: null, siteAttractiveness: null, systemRisk: null, powerBalance: 40 }, scoresByYear: { "2030": { infrastructureDemand: null, siteAttractiveness: null, systemRisk: null, powerBalance: 40 } }, categoryScoresByYear: {}, demandMwByYear: {}, confidence: 60, coverage: 60, valueKind: "reported", updatedAt: "2026-01-01", contributions: [], contributionsByYear: {}, sourceIds: [], assetCount: 0, assetSummary: { total: 0, operational: 0, planned: 0, dataCentres: 0, waterInfrastructure: 0, officialVerified: 0, communityMapped: 0 } } } as GeographyFeature;
    render(<EntityInspector geography={geography} asset={null} lens="powerBalance" year={2030} regionalEnergy={[energy(2030, { low: -120, central: -100, high: -80 }, 12)]} onOpenEvidence={vi.fn()} onAddComparison={vi.fn()} />);
    expect(screen.getByText(/Net balance/)).toBeInTheDocument();
    expect(screen.getByText(/Observed unmet demand/)).toBeInTheDocument();
  });

  it("shows the complete generator record with plain-language unavailable values", () => {
    const generator = { type: "Feature", id: "g-1", geometry: { type: "Point", coordinates: [8.5, 50.1] }, properties: { id: "g-1", name: "Main River Plant", category: "power_generation", country: "DE", geographyId: "DE-HE", lifecycle: "operational", technologies: ["gas"], primaryFuel: "Natural gas", secondaryFuel: "Fuel oil", capacityMw: 500, operatingCapacityMw: 500, plannedCapacityMw: 0, technologyMixMw: { gas: 500 }, annualGenerationGwh: { low: 2000, central: 2200, high: 2400 }, commissioningYear: 2015, retirementYear: null, operator: "GridCo", owner: "Public Power", confidence: 91, sourceUrl: "https://generator.example", sourceIds: [] } } as GeneratorFeature;
    render(<EntityInspector geography={null} asset={null} generator={generator} lens="infrastructureDemand" year={2030} onOpenEvidence={vi.fn()} onAddComparison={vi.fn()} />);
    for (const text of ["Natural gas", "Fuel oil", "500 MW", "2,200 GWh (2,000–2,400)", "Operational", "2015", "GridCo", "Public Power", "50.10000, 8.50000", "91%", "Retirement date unavailable", "Source IDs unavailable"]) expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open source record" })).toHaveAttribute("href", "https://generator.example");
  });
});
