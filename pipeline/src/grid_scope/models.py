from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl
from pydantic.alias_generators import to_camel


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        use_enum_values=True,
    )


class ConnectorState(StrEnum):
    CURRENT = "current"
    CACHED = "cached"
    STALE = "stale"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


class ValueKind(StrEnum):
    OBSERVED = "observed"
    REPORTED = "reported"
    ESTIMATED = "estimated"
    INHERITED = "inherited"
    UNAVAILABLE = "unavailable"


class LifecycleState(StrEnum):
    ANNOUNCED = "announced"
    PLANNING_FILED = "planning_filed"
    PERMITTED = "permitted"
    UNDER_CONSTRUCTION = "under_construction"
    OPERATIONAL = "operational"
    PAUSED = "paused"
    CANCELLED = "cancelled"


Score = float | None


class SourceRef(ContractModel):
    id: str
    name: str
    tier: str = Field(pattern=r"^[ABCD]$")
    url: HttpUrl
    published_at: AwareDatetime | None = None


class ScoreContribution(ContractModel):
    id: str
    label: str
    raw_value: float | None
    unit: str | None
    points: float = Field(ge=0, le=100)
    max_points: float = Field(gt=0, le=100)
    value_kind: ValueKind
    source_ids: list[str] = Field(default_factory=list)
    normalization: str


class LensScores(ContractModel):
    infrastructure_demand: Score = Field(default=None, ge=0, le=100)
    site_attractiveness: Score = Field(default=None, ge=0, le=100)
    system_risk: Score = Field(default=None, ge=0, le=100)


class RegionProperties(ContractModel):
    id: str
    name: str
    country: str = Field(min_length=2, max_length=2)
    score_year: int = Field(ge=2026, le=2031)
    scores: LensScores
    confidence: float = Field(ge=0, le=100)
    coverage: float = Field(ge=0, le=100)
    value_kind: ValueKind
    updated_at: AwareDatetime
    contributions: list[ScoreContribution] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    population: int | None = Field(default=None, ge=0)


class ProjectProperties(ContractModel):
    id: str
    name: str
    region_id: str
    lifecycle: LifecycleState
    capacity_mw: float | None = Field(default=None, ge=0)
    target_year: int | None = Field(default=None, ge=2026, le=2031)
    value_kind: ValueKind
    source_ids: list[str] = Field(default_factory=list)


class EvidenceClaim(ContractModel):
    id: str
    entity_id: str
    summary: str
    source_id: str
    value_kind: ValueKind
    observed_at: AwareDatetime


class ConnectorStatus(ContractModel):
    id: str
    state: ConnectorState
    checked_at: AwareDatetime
    last_success_at: AwareDatetime | None = None
    message: str | None = None


class ArtifactPaths(ContractModel):
    regions: str
    projects: str
    evidence: str


class SnapshotManifest(ContractModel):
    snapshot_id: str
    generated_at: AwareDatetime
    model_version: str
    active_years: list[int] = Field(min_length=6, max_length=6)
    artifacts: ArtifactPaths
    connectors: list[ConnectorStatus]
