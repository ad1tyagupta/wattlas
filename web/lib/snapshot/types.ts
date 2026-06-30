export type LensKey =
  | "infrastructureDemand"
  | "siteAttractiveness"
  | "systemRisk"
  | "powerBalance";

export type LensScores = {
  infrastructureDemand: number | null;
  siteAttractiveness: number | null;
  systemRisk: number | null;
  powerBalance?: number | null;
};

export type InfrastructureCategory = "combined" | "data_centre" | "water_infrastructure";
export type GenerationTechnology = "solar" | "wind" | "hydro" | "nuclear" | "gas" | "coal" | "oil" | "biomass" | "geothermal" | "other";
export type GeographyLevel = "country" | "admin_1" | "admin_2";
export type DemandRange = { low: number; central: number; high: number };

export type ScoreContribution = {
  id: string;
  label: string;
  rawValue: number | null;
  unit: string | null;
  points: number;
  maxPoints: number;
  valueKind: "observed" | "reported" | "estimated" | "inherited" | "unavailable";
  sourceIds: string[];
  normalization: string;
};

export type RegionProperties = {
  id: string;
  name: string;
  country: string;
  scoreYear: number;
  scores: LensScores;
  scoresByYear: Record<string, LensScores>;
  confidence: number;
  coverage: number;
  valueKind: "observed" | "reported" | "estimated" | "inherited" | "unavailable";
  updatedAt: string;
  contributions: ScoreContribution[];
  contributionsByYear: Record<string, ScoreContribution[]>;
  sourceIds: string[];
  population?: number | null;
  populationYear?: number;
  populationSourceYear?: number | null;
  populationValueKind?: RegionProperties["valueKind"];
  populationConfidence?: number;
  powerBalanceYear?: number;
  powerBalanceCoverage?: number | null;
  powerBalanceValueKind?: RegionProperties["valueKind"];
  clusterId?: string | null;
};

export type RegionFeature = GeoJSON.Feature<GeoJSON.Geometry, RegionProperties> & {
  id: string;
};

export type RegionCollection = GeoJSON.FeatureCollection<GeoJSON.Geometry, RegionProperties>;

export type GeographyProperties = RegionProperties & {
  level: GeographyLevel;
  parentId: string | null;
  peerLevel: GeographyLevel;
  categoryScoresByYear: Record<string, Record<InfrastructureCategory, LensScores>>;
  demandMwByYear: Record<string, Record<InfrastructureCategory, DemandRange | null>>;
  assetCount: number;
  assetSummary: AssetSummary;
};
export type AssetSummary = {
  total: number;
  operational: number;
  planned: number;
  dataCentres: number;
  waterInfrastructure: number;
  officialVerified: number;
  communityMapped: number;
};
export type GeographyFeature = GeoJSON.Feature<GeoJSON.Geometry, GeographyProperties> & { id: string };
export type GeographyCollection = GeoJSON.FeatureCollection<GeoJSON.Geometry, GeographyProperties>;

export type AssetProperties = {
  id: string;
  name: string;
  geographyId: string;
  category: Exclude<InfrastructureCategory, "combined">;
  subtype: "hyperscale" | "colocation" | "cloud" | "ai_hpc" | "other_data_centre" | "desalination" | "wastewater" | "water_reuse" | "pipeline_pumping" | "reservoir";
  lifecycle: "announced" | "planning_filed" | "permitted" | "under_construction" | "operational" | "paused" | "cancelled";
  demandMw: DemandRange | null;
  targetYear?: number | null;
  locationPrecision: "exact" | "city_centroid" | "region_centroid";
  valueKind: "observed" | "reported" | "estimated" | "inherited" | "unavailable";
  sourceIds: string[];
  operator?: string | null;
  owner?: string | null;
  website?: string | null;
  facilityRef?: string | null;
  address?: {
    street?: string | null;
    houseNumber?: string | null;
    city?: string | null;
    state?: string | null;
    postcode?: string | null;
    country?: string | null;
  } | null;
  startDate?: string | null;
  openingDate?: string | null;
  reportedPower?: string | null;
  admin1Id?: string | null;
  country: string;
  confidence: number;
  assumptionId?: string;
  sourceType: "community_mapped" | "official_verified";
  sourceUrl?: string | null;
  externalIds: Record<string, string>;
  lastObservedAt?: string | null;
};
export type AssetFeature = GeoJSON.Feature<GeoJSON.Point, AssetProperties> & { id: string };
export type AssetCollection = GeoJSON.FeatureCollection<GeoJSON.Point, AssetProperties>;

export type ProjectProperties = {
  id: string;
  name: string;
  regionId: string;
  entityType: "cluster";
  valueKind: "estimated";
  sourceIds: string[];
  confidence: number;
};

export type ProjectCollection = GeoJSON.FeatureCollection<GeoJSON.Point, ProjectProperties>;

export type ConnectorStatus = {
  id: string;
  state: "current" | "cached" | "stale" | "failed" | "not_configured";
  checkedAt: string;
  lastSuccessAt: string | null;
  message: string | null;
};

export type SnapshotManifest = {
  snapshotId: string;
  generatedAt: string;
  modelVersion: string;
  activeYears: number[];
  artifacts: {
    countries: string; admin1: string; regions: string; assets: string; evidence: string;
    regionalEnergy?: string; generatorOverview?: string; generatorIndex?: string;
  };
  coverage: {
    countries: number;
    regions: number;
    admin1Regions: number;
    countriesWithAdmin1: number;
    assets: number;
    dataCentres: number;
    waterInfrastructure: number;
    powerSourceRecords?: number;
    canonicalPowerPlants?: number;
    publishedPowerPlants?: number;
    generatorRegions?: number;
    regionalEnergyRegions?: number;
  };
  boundaryDisclaimer: string | null;
  connectors: ConnectorStatus[];
};

export type MetricRange = { low: number; central: number; high: number };
export type RegionalEnergyForecast = {
  geographyId?: string; year: number;
  metrics: {
    demandGwh: MetricRange; localGenerationGwh: MetricRange | null;
    localGenerationGapGwh: MetricRange | null; netBalanceGwh: MetricRange | null;
    observedUnmetDemandGwh: number | null; installedCapacityMw: number | null;
    dependableCapacityMw: MetricRange | null; peakDemandMw: MetricRange;
  };
  powerBalance?: { score: number | null; coverage: number; status: "rankable" | "not_yet_rankable"; contributions: Array<Omit<ScoreContribution, "points"> & { points: number | null }> };
  methodId: string; sourceIds: string[]; confidence: number; coverage: number;
  valueKind: RegionProperties["valueKind"]; appliedIncrementIds: string[];
  metricLineage: Record<string, { sourceIds: string[]; methodId: string; valueKind: RegionProperties["valueKind"]; [key: string]: unknown }>;
};
export type RegionalEnergyData = Record<string, RegionalEnergyForecast[]>;

export type GeneratorProperties = {
  id: string; category: "power_generation"; country: string; geographyId: string;
  lifecycle?: string; technologies: GenerationTechnology[]; capacityMw: number;
  operatingCapacityMw: number; plannedCapacityMw: number;
  technologyMixMw: Partial<Record<GenerationTechnology, number>>; sourceIds: string[];
  commissioningYear?: number | null; retirementYear?: number | null; targetYear?: number | null;
  [key: string]: unknown;
};
export type GeneratorFeature = GeoJSON.Feature<GeoJSON.Point, GeneratorProperties> & { id: string };
export type GeneratorCollection = GeoJSON.FeatureCollection<GeoJSON.Point, GeneratorProperties>;
export type GeneratorOverviewCollection = GeoJSON.FeatureCollection<GeoJSON.Point, {
  geographyId: string; country: string; count: number; capacityMw: number;
  operatingCapacityMw: number; plannedCapacityMw: number;
  technologyMixMw: Partial<Record<GenerationTechnology, number>>; dominantTechnology: GenerationTechnology;
}>;
export type GeneratorIndex = {
  countries: Record<string, { bbox: [number, number, number, number]; path: string; featureCount: number; checksum: string; bytes: number; capacityMw: number }>;
  totals: { featureCount: number; capacityMw: number };
};

export type LayerError = { kind: "aborted" | "network" | "http" | "invalid" | "missing"; message: string; recoverable: true; path: string };
export type LayerResult<T> = { ok: true; data: T } | { ok: false; error: LayerError };

export type EvidenceSource = {
  id: string;
  name: string;
  tier: "A" | "B" | "C" | "D";
  url: string;
  publishedAt: string;
};

export type EvidenceData = {
  sources: EvidenceSource[];
  claims: Array<{
    id: string;
    entityId: string;
    summary: string;
    sourceIds: string[];
    valueKind: string;
    observedAt: string;
  }>;
};

export type SnapshotData = {
  manifest: SnapshotManifest;
  countries: GeographyCollection;
  admin1: GeographyCollection;
  regions: GeographyCollection;
  assets: AssetCollection;
  evidence: EvidenceData;
};
