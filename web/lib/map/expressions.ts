import type { ExpressionSpecification } from "maplibre-gl";

import type { LensKey } from "@/lib/snapshot/types";

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
