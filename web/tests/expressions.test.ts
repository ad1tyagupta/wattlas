import { describe, expect, it } from "vitest";

import {
  assetColor,
  assetStrokeColorExpression,
  countryBorderWidthExpression,
  mapColorExpression,
  admin1LineOpacityExpression,
  admin1LineWidthExpression,
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
  it("reveals ADM1 boundaries progressively from the initial world zoom", () => {
    expect(admin1LineWidthExpression()).toEqual(["interpolate", ["linear"], ["zoom"], 1, 0.35, 3, 0.8, 6, 1.25]);
    expect(admin1LineOpacityExpression()).toEqual(["interpolate", ["linear"], ["zoom"], 1, 0.28, 3, 0.65, 6, 0.9]);
  });

  it("uses an explicit unavailable branch and diverging Power Balance palette", () => {
    expect(mapColorExpression("powerBalance")).toEqual([
      "case",
      ["==", ["get", "activeScore"], null],
      "#142321",
      ["interpolate", ["linear"], ["to-number", ["get", "activeScore"]], 0, "#4D8879", 35, "#71817D", 55, "#A4864E", 75, "#D66F5F"],
    ]);
  });

  it("keeps national borders stronger than regional boundaries", () => {
    expect(countryBorderWidthExpression("AE")).toEqual([
      "case",
      ["==", ["get", "id"], "AE"],
      3.2,
      1.6,
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
