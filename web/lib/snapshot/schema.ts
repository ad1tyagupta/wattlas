import { z } from "zod";

export const connectorStateSchema = z.enum([
  "current",
  "cached",
  "stale",
  "failed",
  "not_configured",
]);

export const valueKindSchema = z.enum([
  "observed",
  "reported",
  "estimated",
  "inherited",
  "unavailable",
]);

export const lifecycleStateSchema = z.enum([
  "announced",
  "planning_filed",
  "permitted",
  "under_construction",
  "operational",
  "paused",
  "cancelled",
]);

export const geographyLevelSchema = z.enum(["country", "admin_1", "admin_2"]);
export const assetCategorySchema = z.enum(["data_centre", "water_infrastructure"]);
export const assetSubtypeSchema = z.enum([
  "hyperscale", "colocation", "cloud", "ai_hpc", "other_data_centre",
  "desalination", "wastewater", "water_reuse", "pipeline_pumping", "reservoir",
]);
export const locationPrecisionSchema = z.enum(["exact", "city_centroid", "region_centroid"]);
export const demandRangeSchema = z.object({
  low: z.number().nonnegative(),
  central: z.number().nonnegative(),
  high: z.number().nonnegative(),
}).refine(({ low, central, high }) => low <= central && central <= high, {
  message: "Demand range must satisfy low <= central <= high",
});

export const scoreSchema = z.number().min(0).max(100).nullable();

export const lensScoresSchema = z.object({
  infrastructureDemand: scoreSchema,
  siteAttractiveness: scoreSchema,
  systemRisk: scoreSchema,
});

export const scoreContributionSchema = z.object({
  id: z.string(),
  label: z.string(),
  rawValue: z.number().nullable(),
  unit: z.string().nullable(),
  points: z.number().min(0).max(100),
  maxPoints: z.number().positive().max(100),
  valueKind: valueKindSchema,
  sourceIds: z.array(z.string()),
  normalization: z.string(),
});

export const connectorStatusSchema = z.object({
  id: z.string(),
  state: connectorStateSchema,
  checkedAt: z.string().datetime(),
  lastSuccessAt: z.string().datetime().nullable(),
  message: z.string().nullable(),
});

export const manifestSchema = z.object({
  snapshotId: z.string().min(1),
  generatedAt: z.string().datetime(),
  modelVersion: z.string().min(1),
  activeYears: z
    .array(z.number().int().min(2026).max(2031))
    .length(6)
    .refine((years) => years.join(",") === "2026,2027,2028,2029,2030,2031"),
  artifacts: z.object({
    regions: z.string(),
    projects: z.string(),
    evidence: z.string(),
  }),
  connectors: z.array(connectorStatusSchema),
});

export const regionPropertiesSchema = z.object({
  id: z.string(),
  name: z.string(),
  country: z.string().length(2),
  scoreYear: z.number().int().min(2026).max(2031),
  scores: lensScoresSchema,
  confidence: z.number().min(0).max(100),
  coverage: z.number().min(0).max(100),
  valueKind: valueKindSchema,
  updatedAt: z.string().datetime(),
  contributions: z.array(scoreContributionSchema),
  sourceIds: z.array(z.string()),
  population: z.number().int().nonnegative().nullable().optional(),
});

export const geographyPropertiesSchema = z.object({
  id: z.string(),
  name: z.string(),
  country: z.string().length(2),
  level: geographyLevelSchema,
  parentId: z.string().nullable(),
  peerLevel: geographyLevelSchema.default("country"),
  scoreYear: z.number().int().min(2026).max(2031),
  scores: lensScoresSchema,
  confidence: z.number().min(0).max(100),
  coverage: z.number().min(0).max(100),
  valueKind: valueKindSchema,
  updatedAt: z.string().datetime(),
  contributions: z.array(scoreContributionSchema),
  sourceIds: z.array(z.string()),
  population: z.number().int().nonnegative().nullable().optional(),
});

export const assetPropertiesSchema = z.object({
  id: z.string(),
  name: z.string(),
  geographyId: z.string(),
  category: assetCategorySchema,
  subtype: assetSubtypeSchema,
  lifecycle: lifecycleStateSchema,
  demandMw: demandRangeSchema.nullable().default(null),
  targetYear: z.number().int().min(2026).max(2031).nullable().optional(),
  locationPrecision: locationPrecisionSchema,
  valueKind: valueKindSchema,
  sourceIds: z.array(z.string()),
}).refine(({ demandMw, sourceIds }) => demandMw === null || sourceIds.length > 0, {
  message: "Demand-contributing assets require at least one source",
  path: ["sourceIds"],
});

export const regionFeatureCollectionSchema = z.object({
  type: z.literal("FeatureCollection"),
  features: z.array(
    z.object({
      type: z.literal("Feature"),
      id: z.string(),
      geometry: z.record(z.string(), z.unknown()),
      properties: regionPropertiesSchema,
    }),
  ),
});

export type ConnectorState = z.infer<typeof connectorStateSchema>;
export type SnapshotManifest = z.infer<typeof manifestSchema>;
export type RegionProperties = z.infer<typeof regionPropertiesSchema>;
export type GeographyProperties = z.infer<typeof geographyPropertiesSchema>;
export type AssetProperties = z.infer<typeof assetPropertiesSchema>;
