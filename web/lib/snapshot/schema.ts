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
export const assetSummarySchema = z.object({
  total: z.number().int().nonnegative(),
  operational: z.number().int().nonnegative(),
  planned: z.number().int().nonnegative(),
  dataCentres: z.number().int().nonnegative(),
  waterInfrastructure: z.number().int().nonnegative(),
  officialVerified: z.number().int().nonnegative(),
  communityMapped: z.number().int().nonnegative(),
});

export const scoreSchema = z.number().min(0).max(100).nullable();

export const lensScoresSchema = z.object({
  infrastructureDemand: scoreSchema,
  siteAttractiveness: scoreSchema,
  systemRisk: scoreSchema,
});

export const categoryScoresSchema = z.object({
  combined: lensScoresSchema,
  data_centre: lensScoresSchema,
  water_infrastructure: lensScoresSchema,
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
    countries: z.string(),
    regions: z.string(),
    assets: z.string(),
    evidence: z.string(),
  }),
  coverage: z.object({
    countries: z.number().int().nonnegative(),
    regions: z.number().int().nonnegative(),
    assets: z.number().int().nonnegative(),
    dataCentres: z.number().int().nonnegative(),
    waterInfrastructure: z.number().int().nonnegative(),
  }),
  boundaryDisclaimer: z.string().nullable(),
  connectors: z.array(connectorStatusSchema),
});

export const regionPropertiesSchema = z.object({
  id: z.string(),
  name: z.string(),
  country: z.string().length(2),
  scoreYear: z.number().int().min(2026).max(2031),
  scores: lensScoresSchema,
  scoresByYear: z.record(z.string(), lensScoresSchema),
  confidence: z.number().min(0).max(100),
  coverage: z.number().min(0).max(100),
  valueKind: valueKindSchema,
  updatedAt: z.string().datetime(),
  contributions: z.array(scoreContributionSchema),
  contributionsByYear: z.record(z.string(), z.array(scoreContributionSchema)),
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
  scoresByYear: z.record(z.string(), lensScoresSchema),
  categoryScoresByYear: z.record(z.string(), categoryScoresSchema),
  demandMwByYear: z.record(z.string(), z.object({
    combined: demandRangeSchema.nullable(),
    data_centre: demandRangeSchema.nullable(),
    water_infrastructure: demandRangeSchema.nullable(),
  })),
  confidence: z.number().min(0).max(100),
  coverage: z.number().min(0).max(100),
  valueKind: valueKindSchema,
  updatedAt: z.string().datetime(),
  contributions: z.array(scoreContributionSchema),
  contributionsByYear: z.record(z.string(), z.array(scoreContributionSchema)),
  sourceIds: z.array(z.string()),
  assetCount: z.number().int().nonnegative(),
  assetSummary: assetSummarySchema.default({
    total: 0,
    operational: 0,
    planned: 0,
    dataCentres: 0,
    waterInfrastructure: 0,
    officialVerified: 0,
    communityMapped: 0,
  }),
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
  operator: z.string().nullable().optional(),
  country: z.string().length(2),
  confidence: z.number().min(0).max(100),
  assumptionId: z.string().optional(),
  sourceType: z.enum(["community_mapped", "official_verified"]).default("official_verified"),
  sourceUrl: z.string().url().nullable().optional(),
  externalIds: z.record(z.string(), z.string()).default({}),
  lastObservedAt: z.string().datetime().nullable().optional(),
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
      geometry: z.custom<GeoJSON.Geometry>(),
      properties: regionPropertiesSchema,
    }),
  ),
});

export const geographyFeatureCollectionSchema = z.object({
  type: z.literal("FeatureCollection"),
  metadata: z.object({
    source: z.string().optional(),
    disclaimer: z.string().optional(),
  }).optional(),
  features: z.array(z.object({
    type: z.literal("Feature"),
    id: z.string(),
    geometry: z.custom<GeoJSON.Geometry>(),
    properties: geographyPropertiesSchema,
  })),
});

export const assetFeatureCollectionSchema = z.object({
  type: z.literal("FeatureCollection"),
  features: z.array(z.object({
    type: z.literal("Feature"),
    id: z.string(),
    geometry: z.object({
      type: z.literal("Point"),
      coordinates: z.tuple([z.number(), z.number()]),
    }),
    properties: assetPropertiesSchema,
  })),
});

export const evidenceSchema = z.object({
  sources: z.array(z.object({
    id: z.string(),
    name: z.string(),
    tier: z.enum(["A", "B", "C", "D"]),
    url: z.string().url(),
    publishedAt: z.string().datetime().nullable().optional(),
  })),
  claims: z.array(z.object({
    id: z.string(),
    entityId: z.string(),
    summary: z.string(),
    sourceIds: z.array(z.string()),
    valueKind: valueKindSchema,
    observedAt: z.string().datetime(),
  })),
});

export type ConnectorState = z.infer<typeof connectorStateSchema>;
export type SnapshotManifest = z.infer<typeof manifestSchema>;
export type RegionProperties = z.infer<typeof regionPropertiesSchema>;
export type GeographyProperties = z.infer<typeof geographyPropertiesSchema>;
export type AssetProperties = z.infer<typeof assetPropertiesSchema>;
