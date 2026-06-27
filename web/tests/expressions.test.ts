import { describe, expect, it } from "vitest";

import { scoreColor } from "@/lib/map/expressions";

describe("scoreColor", () => {
  it("keeps unavailable regions neutral", () => {
    expect(scoreColor(null, "infrastructureDemand")).toBe("#142321");
  });

  it("uses amber for high infrastructure demand", () => {
    expect(scoreColor(85, "infrastructureDemand")).toBe("#E2B45C");
  });

  it("uses rust for high system risk", () => {
    expect(scoreColor(85, "systemRisk")).toBe("#D66F5F");
  });
});
