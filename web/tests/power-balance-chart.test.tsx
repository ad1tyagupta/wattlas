import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PowerBalanceChart } from "@/components/inspector/power-balance-chart";
import type { RegionalEnergyForecast } from "@/lib/snapshot/types";

afterEach(cleanup);

const rows = Array.from({ length: 6 }, (_, i) => ({ year: 2026 + i, metrics: { demandGwh: { low: 100 + i, central: 110 + i, high: 120 + i }, localGenerationGwh: { low: 80, central: 90, high: 100 }, localGenerationGapGwh: { low: 0, central: 20, high: 40 }, netBalanceGwh: null, observedUnmetDemandGwh: null, installedCapacityMw: 50, dependableCapacityMw: { low: 30, central: 35, high: 40 }, peakDemandMw: { low: 20, central: 25, high: 30 } }, methodId: "m1", sourceIds: ["s1"], confidence: 70, coverage: 80, valueKind: "estimated", appliedIncrementIds: [], metricLineage: {} })) as RegionalEnergyForecast[];

describe("PowerBalanceChart", () => {
  it("renders an accessible responsive SVG and a complete table fallback", () => {
    render(<PowerBalanceChart forecasts={[...rows].reverse()} />);
    expect(screen.getByRole("img", { name: /2026 to 2031 demand versus local generation/i })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /demand versus local generation data/i })).toBeInTheDocument();
    expect(screen.getAllByText("2026").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2031").length).toBeGreaterThan(0);
    expect(screen.getByText("100–120 GWh")).toBeInTheDocument();
    expect(screen.getAllByText("80–100 GWh")).toHaveLength(6);
  });

  it.each([
    ["missing year", rows.slice(0, 5)],
    ["duplicate year", [...rows.slice(0, 5), rows[0]]],
    ["non-finite range", rows.map((row, index) => index ? row : ({ ...row, metrics: { ...row.metrics, demandGwh: { low: 1, central: Number.NaN, high: 3 } } }))],
    ["unordered range", rows.map((row, index) => index ? row : ({ ...row, metrics: { ...row.metrics, demandGwh: { low: 30, central: 20, high: 10 } } }))],
  ])("renders a controlled unavailable state for %s", (_label, forecasts) => {
    render(<PowerBalanceChart forecasts={forecasts as RegionalEnergyForecast[]} />);
    expect(screen.getByRole("status")).toHaveTextContent(/chart unavailable/i);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
