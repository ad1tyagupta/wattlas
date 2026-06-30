import type { ExpressionSpecification } from "maplibre-gl";

import type { GenerationTechnology } from "@/lib/snapshot/types";

export const GENERATOR_COLORS: Record<GenerationTechnology, string> = {
  solar: "#E7B84B",
  wind: "#55C7D9",
  hydro: "#4E8EDB",
  nuclear: "#A98AE8",
  gas: "#E07A5F",
  coal: "#6F7782",
  oil: "#B88762",
  biomass: "#78B77A",
  geothermal: "#D98255",
  other: "#9AA6A4",
};

export function generatorColor(technology: GenerationTechnology): string {
  return GENERATOR_COLORS[technology];
}

export function generatorColorExpression(property = "dominantTechnology"): ExpressionSpecification {
  return ["match", ["get", property], ...Object.entries(GENERATOR_COLORS).flat(), GENERATOR_COLORS.other] as unknown as ExpressionSpecification;
}

export function generatorTechnologyExpression(): ExpressionSpecification {
  return ["match", ["at", 0, ["get", "technologies"]], ...Object.entries(GENERATOR_COLORS).flat(), GENERATOR_COLORS.other] as unknown as ExpressionSpecification;
}
