export type LensKey =
  | "infrastructureDemand"
  | "siteAttractiveness"
  | "systemRisk";

export type LensScores = Record<LensKey, number | null>;

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
  clusterId?: string | null;
};

export type RegionFeature = GeoJSON.Feature<GeoJSON.Geometry, RegionProperties> & {
  id: string;
};

export type RegionCollection = GeoJSON.FeatureCollection<GeoJSON.Geometry, RegionProperties>;

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
  artifacts: { regions: string; projects: string; evidence: string };
  connectors: ConnectorStatus[];
};

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
  regions: RegionCollection;
  projects: ProjectCollection;
  evidence: EvidenceData;
};
