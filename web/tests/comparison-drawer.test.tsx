import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ComparisonDrawer } from "@/components/comparison/comparison-drawer";
import type { RegionFeature, RegionalEnergyData } from "@/lib/snapshot/types";

const region = (id: string, name: string) => ({ type: "Feature", id, geometry: { type: "Polygon", coordinates: [] }, properties: { id, name, country: "US", scoreYear: 2030, scores: { infrastructureDemand: 1, siteAttractiveness: 2, systemRisk: 3, powerBalance: 4 }, scoresByYear: { "2030": { infrastructureDemand: 1, siteAttractiveness: 2, systemRisk: 3, powerBalance: 4 } }, confidence: 99, coverage: 99, valueKind: "observed", updatedAt: "2026-01-01", contributions: [], contributionsByYear: {}, sourceIds: [] } }) as RegionFeature;
const energy: RegionalEnergyData = Object.fromEntries(["A", "B"].map((id) => [id, [{ year: 2030, metrics: { demandGwh: { low: 900, central: 1000.5, high: 1100 }, localGenerationGwh: { low: 700, central: 800, high: 900 }, localGenerationGapGwh: { low: 0, central: 200.25, high: 400 }, netBalanceGwh: null, observedUnmetDemandGwh: null, installedCapacityMw: 100, dependableCapacityMw: { low: 50, central: 60, high: 70 }, peakDemandMw: { low: 10, central: 20, high: 30 } }, powerBalance: { score: 44, coverage: 73, status: "rankable", contributions: [] }, methodId: "m", sourceIds: ["s"], confidence: 61.5, coverage: 72, valueKind: "estimated", appliedIncrementIds: [], metricLineage: {} }]]));

describe("ComparisonDrawer", () => {
  it("uses active-year energy metadata and consistent one-decimal metrics for Power Balance", () => {
    render(<ComparisonDrawer regions={[region("A", "Alpha"), region("B", "Beta")]} lens="powerBalance" year={2030} regionalEnergy={energy} onClose={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getAllByText("Confidence 61.5% · Estimated")).toHaveLength(2);
    expect(screen.getAllByText("1,000.5 GWh")).toHaveLength(2);
    expect(screen.getAllByText("200.3 GWh")).toHaveLength(2);
    expect(screen.getAllByText("73%")).toHaveLength(2);
    expect(screen.queryByText(/Confidence 99%/)).not.toBeInTheDocument();
  });
});
