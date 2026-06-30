import type { ExpressionSpecification } from "maplibre-gl";

import type { InfrastructureCategory, LensKey } from "@/lib/snapshot/types";

const ramps: Record<LensKey, Array<[number, string]>> = {
  infrastructureDemand: [
    [0, "#1B3430"],
    [45, "#3D7467"],
    [65, "#A4864E"],
    [80, "#E2B45C"],
  ],
  siteAttractiveness: [
    [0, "#1A2C2A"],
    [45, "#32685E"],
    [65, "#55A28E"],
    [80, "#72D9BD"],
  ],
  systemRisk: [
    [0, "#26312F"],
    [45, "#72564D"],
    [65, "#A85E51"],
    [80, "#D66F5F"],
  ],
  powerBalance: [
    [0, "#4D8879"],
    [35, "#71817D"],
    [55, "#A4864E"],
    [75, "#D66F5F"],
  ],
};

export function scoreColor(score: number | null, lens: LensKey): string {
  if (score === null) return "#142321";
  const ramp = ramps[lens];
  return [...ramp].reverse().find(([threshold]) => score >= threshold)?.[1] ?? ramp[0][1];
}

export function mapColorExpression(lens: LensKey): ExpressionSpecification {
  const ramp = ramps[lens];
  return [
    "case",
    ["==", ["get", "activeScore"], null],
    "#142321",
    [
      "interpolate",
      ["linear"],
      ["to-number", ["get", "activeScore"]],
      ...ramp.flat(),
    ],
  ] as ExpressionSpecification;
}

export function countryBorderWidthExpression(selectedId: string | null): ExpressionSpecification {
  return [
    "case",
    ["==", ["get", "id"], selectedId ?? ""],
    3.2,
    1.6,
  ] as ExpressionSpecification;
}

export function admin1LineWidthExpression(): ExpressionSpecification {
  return ["interpolate", ["linear"], ["zoom"], 1, 0.35, 3, 0.8, 6, 1.25] as ExpressionSpecification;
}

export function admin1LineOpacityExpression(): ExpressionSpecification {
  return ["interpolate", ["linear"], ["zoom"], 1, 0.28, 3, 0.65, 6, 0.9] as ExpressionSpecification;
}

export function assetColor(category: Exclude<InfrastructureCategory, "combined">): string {
  return category === "data_centre" ? "#8FAEFF" : "#72D9BD";
}

export function assetStrokeColorExpression(): ExpressionSpecification {
  return [
    "case",
    ["==", ["get", "sourceType"], "official_verified"],
    "#F1F6F4",
    "#07100F",
  ] as ExpressionSpecification;
}
