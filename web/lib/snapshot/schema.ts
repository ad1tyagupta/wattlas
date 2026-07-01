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
export const assetCategorySchema = z.enum(["data_centre", "water_infrastructure", "power_generation"]);
export const generationTechnologySchema = z.enum([
  "solar", "wind", "hydro", "nuclear", "gas", "coal", "oil",
  "biomass", "geothermal", "other",
]);
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
  powerBalance: scoreSchema.default(null),
});

export const categoryScoresSchema = z.object({
  combined: lensScoresSchema,
  data_centre: lensScoresSchema,
  water_infrastructure: lensScoresSchema,
});

export const scoreContributionSchema = z.object({
  id: z.string().trim().min(1),
  label: z.string().trim().min(1),
  rawValue: z.number().nullable(),
  unit: z.string().trim().min(1).nullable(),
  points: z.number().min(0).max(100).nullable(),
  maxPoints: z.number().positive().max(100),
  valueKind: valueKindSchema,
  sourceIds: z.array(z.string().trim().min(1)).refine((values) => new Set(values).size === values.length, "Source IDs must be unique"),
  normalization: z.string().trim().min(1),
  methodVersion: z.string().trim().min(1),
}).strict().superRefine((contribution, context) => {
  const unavailable = contribution.valueKind === "unavailable";
  if (unavailable && (contribution.rawValue !== null || contribution.points !== null)) {
    context.addIssue({ code: "custom", message: "Unavailable contributions require null values" });
  }
  if (!unavailable && (contribution.rawValue === null || contribution.points === null)) {
    context.addIssue({ code: "custom", message: "Available contributions require values" });
  }
  if (contribution.points !== null && contribution.points > contribution.maxPoints) {
    context.addIssue({ code: "custom", message: "Contribution points cannot exceed maxPoints", path: ["points"] });
  }
});

export const connectorStatusSchema = z.object({
  id: z.string(),
  state: connectorStateSchema,
  checkedAt: z.string().datetime(),
  lastSuccessAt: z.string().datetime().nullable(),
  observationDate: z.string().date().nullable().optional(),
  message: z.string().nullable(),
}).strict();

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
    admin1: z.string(),
    regions: z.string(),
    assets: z.string(),
    evidence: z.string(),
    regionalEnergy: z.string().optional(),
    generatorOverview: z.string().optional(),
    generatorIndex: z.string().optional(),
  }).strict(),
  coverage: z.object({
    countries: z.number().int().nonnegative(),
    regions: z.number().int().nonnegative(),
    admin1Regions: z.number().int().nonnegative(),
    countriesWithAdmin1: z.number().int().nonnegative(),
    assets: z.number().int().nonnegative(),
    dataCentres: z.number().int().nonnegative(),
    waterInfrastructure: z.number().int().nonnegative(),
    powerSourceRecords: z.number().int().nonnegative().optional(),
    powerSourceRecordsBySource: z.record(z.string().min(1), z.number().int().nonnegative()).optional(),
    canonicalPowerPlants: z.number().int().nonnegative().optional(),
    canonicalPowerUnits: z.number().int().nonnegative().optional(),
    publishedPowerPlants: z.number().int().nonnegative().optional(),
    generatorRegions: z.number().int().nonnegative().optional(),
    regionalEnergyRegions: z.number().int().nonnegative().optional(),
  }).strict(),
  quality: z.object({
    countryDemandReconciled: z.boolean(),
    generatorArtifactsReconciled: z.boolean(),
    populationBuildFingerprint: z.string().min(1).nullable(),
    demandWeightsBuildFingerprint: z.string().min(1).nullable(),
  }).strict().optional(),
  boundaryDisclaimer: z.string().nullable(),
  connectors: z.array(connectorStatusSchema),
  checksums: z.record(z.string().min(1), z.string().regex(/^[a-f0-9]{64}$/)).optional(),
}).strict();

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
  populationYear: z.number().int().min(2026).max(2031).optional(),
  populationSourceYear: z.number().int().min(1900).max(2031).nullable().optional(),
  populationValueKind: valueKindSchema.optional(),
  populationConfidence: z.number().min(0).max(100).optional(),
  powerBalanceYear: z.number().int().min(2026).max(2031).optional(),
  powerBalanceCoverage: z.number().min(0).max(100).nullable().optional(),
  powerBalanceValueKind: valueKindSchema.optional(),
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
  subtype: assetSubtypeSchema.nullable().optional(),
  lifecycle: lifecycleStateSchema,
  demandMw: demandRangeSchema.nullable().default(null),
  technology: generationTechnologySchema.nullable().optional(),
  secondaryFuel: z.string().nullable().optional(),
  capacityMw: demandRangeSchema.nullable().optional(),
  dependableCapacityMw: demandRangeSchema.nullable().optional(),
  annualGenerationGwh: demandRangeSchema.nullable().optional(),
  commissioningYear: z.number().int().positive().nullable().optional(),
  retirementYear: z.number().int().positive().nullable().optional(),
  plantId: z.string().nullable().optional(),
  unitId: z.string().nullable().optional(),
  targetYear: z.number().int().min(2026).max(2031).nullable().optional(),
  locationPrecision: locationPrecisionSchema,
  valueKind: valueKindSchema,
  sourceIds: z.array(z.string()),
  operator: z.string().nullable().optional(),
  country: z.string().length(2),
  confidence: z.number().min(0).max(100),
  assumptionId: z.string().optional(),
  sourceType: z.enum(["community_mapped", "official_verified", "research_verified", "modelled"]).default("official_verified"),
  sourceUrl: z.string().url().nullable().optional(),
  externalIds: z.record(z.string(), z.string()).default({}),
  lastObservedAt: z.string().datetime().nullable().optional(),
  owner: z.string().nullable().optional(),
  website: z.string().url().nullable().optional(),
  facilityRef: z.string().nullable().optional(),
  address: z.object({
    street: z.string().nullable().optional(),
    houseNumber: z.string().nullable().optional(),
    city: z.string().nullable().optional(),
    state: z.string().nullable().optional(),
    postcode: z.string().nullable().optional(),
    country: z.string().nullable().optional(),
  }).nullable().optional(),
  startDate: z.string().nullable().optional(),
  openingDate: z.string().nullable().optional(),
  reportedPower: z.string().nullable().optional(),
  admin1Id: z.string().nullable().optional(),
}).superRefine((asset, context) => {
  const sourceIdsAreValid = asset.sourceIds.length > 0 && asset.sourceIds.every((sourceId) => sourceId.trim().length > 0);
  if (asset.demandMw !== null && !sourceIdsAreValid) {
    context.addIssue({ code: "custom", message: "Demand-contributing assets require nonblank sources", path: ["sourceIds"] });
  }
  const generationFields = [
    asset.technology, asset.secondaryFuel, asset.capacityMw, asset.dependableCapacityMw,
    asset.annualGenerationGwh, asset.commissioningYear, asset.retirementYear,
    asset.plantId, asset.unitId,
  ];
  if (asset.category === "power_generation") {
    if (asset.subtype != null) {
      context.addIssue({ code: "custom", message: "Power generation cannot have an infrastructure subtype", path: ["subtype"] });
    }
    if (asset.technology == null) {
      context.addIssue({ code: "custom", message: "Power generation requires a technology", path: ["technology"] });
    }
    const hasGenerationMetrics = asset.capacityMw != null || asset.dependableCapacityMw != null || asset.annualGenerationGwh != null;
    if (hasGenerationMetrics && (asset.valueKind === "reported" || asset.valueKind === "estimated") && !sourceIdsAreValid) {
      context.addIssue({ code: "custom", message: "Reported or estimated generation metrics require nonblank sources", path: ["sourceIds"] });
    }
    if (asset.commissioningYear != null && asset.retirementYear != null && asset.retirementYear < asset.commissioningYear) {
      context.addIssue({ code: "custom", message: "Retirement cannot precede commissioning", path: ["retirementYear"] });
    }
    return;
  }
  if (asset.subtype == null) {
    context.addIssue({ code: "custom", message: "Infrastructure assets require a subtype", path: ["subtype"] });
  } else if (asset.category === "data_centre" && !["hyperscale", "colocation", "cloud", "ai_hpc", "other_data_centre"].includes(asset.subtype)) {
    context.addIssue({ code: "custom", message: "Data centres require a data-centre subtype", path: ["subtype"] });
  } else if (asset.category === "water_infrastructure" && !["desalination", "wastewater", "water_reuse", "pipeline_pumping", "reservoir"].includes(asset.subtype)) {
    context.addIssue({ code: "custom", message: "Water infrastructure requires a water subtype", path: ["subtype"] });
  }
  if (generationFields.some((value) => value != null)) {
    context.addIssue({ code: "custom", message: "Infrastructure assets cannot contain generation-only fields", path: ["technology"] });
  }
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
    sourceUrl: z.string().url().optional(),
    license: z.string().optional(),
    indiaBoundaryPerspective: z.string().optional(),
    indiaAttribution: z.string().optional(),
    disclaimer: z.string().optional(),
  }).passthrough().optional(),
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

export const metricRangeSchema = z.object({
  low: z.number().finite(), central: z.number().finite(), high: z.number().finite(),
}).refine(({ low, central, high }) => low <= central && central <= high, {
  message: "Metric range must satisfy low <= central <= high",
});

const nonnegativeMetricRangeSchema = metricRangeSchema.refine(({ low }) => low >= 0, {
  message: "Physical metric ranges cannot be negative",
});

export const powerBalanceMetricsSchema = z.object({
  demandGwh: nonnegativeMetricRangeSchema,
  localGenerationGwh: nonnegativeMetricRangeSchema.nullable(),
  localGenerationGapGwh: metricRangeSchema.nullable(),
  netBalanceGwh: metricRangeSchema.nullable(),
  observedUnmetDemandGwh: z.number().nonnegative().nullable(),
  installedCapacityMw: z.number().nonnegative().nullable(),
  dependableCapacityMw: nonnegativeMetricRangeSchema.nullable(),
  peakDemandMw: nonnegativeMetricRangeSchema,
}).refine((value) => (value.localGenerationGwh === null) === (value.localGenerationGapGwh === null), {
  message: "Local generation and local gap must be available together",
}).refine((value) => value.netBalanceGwh === null || value.localGenerationGwh !== null, {
  message: "Net balance requires available local generation and local gap",
});

const powerBalanceContributionSchema = scoreContributionSchema;

const rankableRegionalEnergyForecastSchema = z.object({
  geographyId: z.string().min(1).optional(),
  year: z.number().int().min(2026).max(2031),
  metrics: powerBalanceMetricsSchema,
  powerBalance: z.object({
    score: scoreSchema, coverage: z.number().min(0).max(100),
    status: z.enum(["rankable", "not_yet_rankable"]),
    contributions: z.array(powerBalanceContributionSchema).default([]),
  }).optional(),
  methodId: z.string().min(1), sourceIds: z.array(z.string().min(1)).min(1),
  confidence: z.number().min(0).max(100), coverage: z.number().min(0).max(100),
  valueKind: valueKindSchema, appliedIncrementIds: z.array(z.string()).default([]),
  metricLineage: z.record(z.string(), z.object({
    sourceIds: z.array(z.string().min(1)).min(1), methodId: z.string().min(1),
    valueKind: valueKindSchema,
  }).passthrough()).default({}),
});

const countryLevelOnlyEnergyForecastSchema = z.object({
  geographyId: z.string().min(1).optional(),
  countryIso3: z.string().regex(/^[A-Z]{3}$/),
  year: z.number().int().min(2026).max(2031),
  availability: z.literal("country_level_only"),
  rankable: z.literal(false),
  metrics: z.null(),
  powerBalance: z.null(),
  countryControl: z.object({
    countryIso3: z.string().regex(/^[A-Z]{3}$/),
    year: z.number().int().min(2026).max(2031),
    sourceYear: z.number().int(),
    demandGwh: nonnegativeMetricRangeSchema,
    sourceIds: z.array(z.string().min(1)).min(1),
    valueKind: valueKindSchema,
    methodId: z.string().min(1),
    confidence: z.number().min(0).max(100),
    coverage: z.number().min(0).max(100),
  }).nullable(),
  reason: z.literal("population_unavailable_for_active_adm1"),
  unavailableGeographyIds: z.array(z.string().min(1)).min(1),
  methodId: z.literal("country-level-only-no-adm1-allocation-v1"),
  sourceIds: z.array(z.string().min(1)).min(1),
  confidence: z.literal(0), coverage: z.literal(0),
  valueKind: z.literal("unavailable"),
});

export const regionalEnergyForecastSchema = z.union([
  rankableRegionalEnergyForecastSchema,
  countryLevelOnlyEnergyForecastSchema,
]);

const regionalEnergyCollectionSchema = z.record(
  z.string().min(1),
  z.array(regionalEnergyForecastSchema).refine(
    (rows) => rows.length === 6 && rows.every((row, index) => row.year === 2026 + index),
    { message: "Regional energy requires ordered 2026-2031 records" },
  ),
).superRefine((regions, context) => {
  for (const [geographyId, rows] of Object.entries(regions)) {
    if (rows.some((row) => row.geographyId !== undefined && row.geographyId !== geographyId)) {
      context.addIssue({ code: "custom", message: "Regional energy geography ID does not match its key", path: [geographyId] });
    }
  }
});

const contributionDefinitionSchema = z.object({
  id: z.string().min(1), label: z.string().min(1), maxPoints: z.number().nonnegative(),
  methodVersion: z.string().min(1), normalization: z.string().min(1), unit: z.string().min(1),
}).strict();
const dynamicContributionSchema = z.object({
  id: z.string().min(1), rawValue: z.number().finite().nullable(),
  points: z.number().nonnegative().nullable(), valueKind: valueKindSchema,
  sourceIds: z.array(z.string().min(1)),
}).strict();
const compactRankableForecastSchema = rankableRegionalEnergyForecastSchema.extend({
  geographyId: z.undefined().optional(),
  powerBalance: z.object({
    score: scoreSchema, coverage: z.number().min(0).max(100),
    status: z.enum(["rankable", "not_yet_rankable"]),
    contributions: z.array(dynamicContributionSchema).default([]),
  }).optional(),
});
const compactCountryLevelOnlySchema = countryLevelOnlyEnergyForecastSchema.extend({
  geographyId: z.undefined().optional(),
});
const compactRegionalEnergyEnvelopeSchema = z.object({
  schemaVersion: z.literal("regional-energy-v2"),
  contributionDefinitions: z.record(z.string().min(1), contributionDefinitionSchema),
  regions: z.record(z.string().min(1), z.array(z.union([
    compactRankableForecastSchema, compactCountryLevelOnlySchema,
  ])).refine(
    (rows) => rows.length === 6 && rows.every((row, index) => row.year === 2026 + index),
    { message: "Regional energy requires ordered 2026-2031 records" },
  )),
}).strict().superRefine((envelope, context) => {
  const used = new Set<string>();
  for (const [id, definition] of Object.entries(envelope.contributionDefinitions)) {
    if (definition.id !== id) context.addIssue({ code: "custom", message: "Contribution definition ID must match its key", path: ["contributionDefinitions", id] });
  }
  for (const [regionId, rows] of Object.entries(envelope.regions)) {
    for (const row of rows) for (const contribution of row.powerBalance?.contributions ?? []) {
      used.add(contribution.id);
      if (!envelope.contributionDefinitions[contribution.id]) context.addIssue({ code: "custom", message: "Unknown contribution definition", path: ["regions", regionId] });
    }
  }
  for (const id of Object.keys(envelope.contributionDefinitions)) {
    if (!used.has(id)) context.addIssue({ code: "custom", message: "Unused contribution definition", path: ["contributionDefinitions", id] });
  }
});

export const regionalEnergySchema = z.union([
  regionalEnergyCollectionSchema,
  compactRegionalEnergyEnvelopeSchema.transform((envelope) => {
    const expanded = Object.fromEntries(Object.entries(envelope.regions).map(([geographyId, rows]) => [
      geographyId,
      rows.map((row) => ({
        ...row,
        geographyId,
        powerBalance: row.powerBalance === null ? null : row.powerBalance === undefined ? undefined : {
          ...row.powerBalance,
          contributions: row.powerBalance.contributions.map((dynamic) => ({
            ...envelope.contributionDefinitions[dynamic.id], ...dynamic,
          })),
        },
      })),
    ]));
    return regionalEnergyCollectionSchema.parse(expanded);
  }),
]);

const generatorYearSchema = z.number().int().min(1800).max(2200).nullable();
const technologyMixSchema = z.partialRecord(generationTechnologySchema, z.number().nonnegative());
const generatorTextSchema = z.string().trim().min(1).max(500).nullable();
const generatorSourceUrlSchema = z.string().url().refine((value) => /^https?:\/\//i.test(value), { message: "Generator source URL must use HTTP(S)" }).nullable();
const capacitiesMatch = (left: number, right: number) => Math.abs(left - right) <= Math.max(1e-6, Math.abs(left) * 1e-12);
export const generatorPropertiesSchema = z.object({
  id: z.string().min(1), category: z.literal("power_generation").default("power_generation"),
  country: z.string().length(2), geographyId: z.string().min(1),
  lifecycle: z.enum(["announced", "planning_filed", "permitted", "under_construction", "operational", "paused", "cancelled", "retired", "decommissioned", "shelved"]).optional(),
  technologies: z.array(generationTechnologySchema).min(1),
  capacityMw: z.number().nonnegative(), operatingCapacityMw: z.number().nonnegative(),
  plannedCapacityMw: z.number().nonnegative(), technologyMixMw: technologyMixSchema,
  commissioningYear: generatorYearSchema.optional(), retirementYear: generatorYearSchema.optional(),
  targetYear: generatorYearSchema.optional(), sourceIds: z.array(z.string().min(1)).min(1),
  name: generatorTextSchema.optional(), primaryFuel: generatorTextSchema.optional(), secondaryFuel: generatorTextSchema.optional(),
  annualGenerationGwh: nonnegativeMetricRangeSchema.nullable().optional(), operator: generatorTextSchema.optional(), owner: generatorTextSchema.optional(),
  confidence: z.number().finite().min(0).max(100).nullable().optional(), sourceUrl: generatorSourceUrlSchema.optional(),
  locationName: generatorTextSchema.optional(), plantId: generatorTextSchema.optional(), unitId: generatorTextSchema.optional(),
}).passthrough().refine((value) => capacitiesMatch(value.capacityMw, value.operatingCapacityMw + value.plannedCapacityMw), {
  message: "Generator capacity must reconcile",
}).refine((value) => capacitiesMatch(value.capacityMw, Object.values(value.technologyMixMw).reduce((a, b) => a + b, 0)), {
  message: "Generator technology mix must reconcile",
}).refine((value) => value.commissioningYear == null || value.retirementYear == null || value.commissioningYear <= value.retirementYear, {
  message: "Generator retirement cannot precede commissioning",
});

const pointGeometrySchema = z.object({
  type: z.literal("Point"),
  coordinates: z.tuple([z.number().min(-180).max(180), z.number().min(-90).max(90)]),
});
export const generatorCountryShardSchema = z.object({
  type: z.literal("FeatureCollection"),
  features: z.array(z.object({ type: z.literal("Feature"), id: z.string().min(1), geometry: pointGeometrySchema, properties: generatorPropertiesSchema })
    .refine((feature) => feature.id === feature.properties.id, { message: "Generator feature and property IDs must match" })),
});

export const generatorOverviewSchema = z.object({
  type: z.literal("FeatureCollection"),
  features: z.array(z.object({
    type: z.literal("Feature"), id: z.string().min(1), geometry: pointGeometrySchema,
    properties: z.object({
      geographyId: z.string().min(1), country: z.string().length(2), count: z.number().int().nonnegative(),
      capacityMw: z.number().nonnegative(), operatingCapacityMw: z.number().nonnegative(),
      plannedCapacityMw: z.number().nonnegative(), technologyMixMw: technologyMixSchema,
      dominantTechnology: generationTechnologySchema,
      lifecycleCounts: z.record(z.string().min(1), z.number().int().nonnegative()).optional(),
    }).refine((value) => capacitiesMatch(value.capacityMw, value.operatingCapacityMw + value.plannedCapacityMw))
      .refine((value) => capacitiesMatch(value.capacityMw, Object.values(value.technologyMixMw).reduce((a, b) => a + b, 0))),
  }).refine((feature) => feature.id === feature.properties.geographyId, { message: "Generator overview ID must match its ADM1" })),
});

const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/);
export const generatorIndexSchema = z.object({
  countries: z.record(z.string().length(2), z.object({
    bbox: z.tuple([z.number().min(-180).max(180), z.number().min(-90).max(90), z.number().min(-180).max(180), z.number().min(-90).max(90)]),
    path: z.string().regex(/^generators\/[A-Z]{2}\.geojson$/), featureCount: z.number().int().nonnegative(),
    checksum: sha256Schema, bytes: z.number().int().positive(), capacityMw: z.number().nonnegative(),
  }).strict()),
  totals: z.object({ featureCount: z.number().int().nonnegative(), capacityMw: z.number().nonnegative() }).strict(),
}).strict().superRefine((index, context) => {
  let featureCount = 0;
  let capacityMw = 0;
  for (const [country, entry] of Object.entries(index.countries)) {
    if (entry.path !== `generators/${country}.geojson`) {
      context.addIssue({ code: "custom", message: "Generator shard path must match its country", path: ["countries", country, "path"] });
    }
    if (entry.bbox[1] > entry.bbox[3]) {
      context.addIssue({ code: "custom", message: "Generator shard latitude bounds are reversed", path: ["countries", country, "bbox"] });
    }
    featureCount += entry.featureCount;
    capacityMw += entry.capacityMw;
  }
  if (featureCount !== index.totals.featureCount || !capacitiesMatch(capacityMw, index.totals.capacityMw)) {
    context.addIssue({ code: "custom", message: "Generator index totals must reconcile", path: ["totals"] });
  }
});

export type ConnectorState = z.infer<typeof connectorStateSchema>;
export type SnapshotManifest = z.infer<typeof manifestSchema>;
export type RegionProperties = z.infer<typeof regionPropertiesSchema>;
export type GeographyProperties = z.infer<typeof geographyPropertiesSchema>;
export type AssetProperties = z.infer<typeof assetPropertiesSchema>;
