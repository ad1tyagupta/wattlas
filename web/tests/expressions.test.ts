import { describe, expect, it } from "vitest";

import {
  assetColor,
  assetStrokeColorExpression,
  countryBorderWidthExpression,
  scoreColor,
} from "@/lib/map/expressions";

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

describe("global map expressions", () => {
  it("keeps national borders stronger than regional boundaries", () => {
    expect(countryBorderWidthExpression("AE")).toEqual([
      "case",
      ["==", ["get", "id"], "AE"],
      3.2,
      1.25,
    ]);
  });

  it("assigns distinct infrastructure colors", () => {
    expect(assetColor("data_centre")).toBe("#8FAEFF");
    expect(assetColor("water_infrastructure")).toBe("#72D9BD");
  });

  it("distinguishes officially verified facilities", () => {
    const expression = JSON.stringify(assetStrokeColorExpression());
    expect(expression).toContain("official_verified");
    expect(expression).toContain("#F1F6F4");
  });
});
