from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, computed_field, model_validator
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


class GeographyLevel(StrEnum):
    COUNTRY = "country"
    ADMIN_1 = "admin_1"
    ADMIN_2 = "admin_2"


class AssetCategory(StrEnum):
    DATA_CENTRE = "data_centre"
    WATER_INFRASTRUCTURE = "water_infrastructure"
    POWER_GENERATION = "power_generation"


class GenerationTechnology(StrEnum):
    SOLAR = "solar"
    WIND = "wind"
    HYDRO = "hydro"
    NUCLEAR = "nuclear"
    GAS = "gas"
    COAL = "coal"
    OIL = "oil"
    BIOMASS = "biomass"
    GEOTHERMAL = "geothermal"
    OTHER = "other"


class AssetSubtype(StrEnum):
    HYPERSCALE = "hyperscale"
    COLOCATION = "colocation"
    CLOUD = "cloud"
    AI_HPC = "ai_hpc"
    OTHER_DATA_CENTRE = "other_data_centre"
    DESALINATION = "desalination"
    WASTEWATER = "wastewater"
    WATER_REUSE = "water_reuse"
    PIPELINE_PUMPING = "pipeline_pumping"
    RESERVOIR = "reservoir"


class LocationPrecision(StrEnum):
    EXACT = "exact"
    CITY_CENTROID = "city_centroid"
    REGION_CENTROID = "region_centroid"


class SourceType(StrEnum):
    COMMUNITY_MAPPED = "community_mapped"
    OFFICIAL_VERIFIED = "official_verified"


Score = float | None


class DemandRange(ContractModel):
    low: float = Field(ge=0)
    central: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> "DemandRange":
        if not self.low <= self.central <= self.high:
            raise ValueError("demand range must satisfy low <= central <= high")
        return self


class MetricRange(ContractModel):
    low: float = Field(allow_inf_nan=False)
    central: float = Field(allow_inf_nan=False)
    high: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> "MetricRange":
        if not self.low <= self.central <= self.high:
            raise ValueError("metric range must satisfy low <= central <= high")
        return self


class PowerBalanceMetrics(ContractModel):
    demand_gwh: MetricRange
    local_generation_gwh: MetricRange
    local_generation_gap_gwh: MetricRange
    net_balance_gwh: MetricRange | None = None
    observed_unmet_demand_gwh: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    installed_capacity_mw: float = Field(ge=0, allow_inf_nan=False)
    dependable_capacity_mw: MetricRange
    peak_demand_mw: MetricRange

    @model_validator(mode="after")
    def physical_inputs_are_non_negative(self) -> "PowerBalanceMetrics":
        non_negative_ranges = (
            self.demand_gwh,
            self.local_generation_gwh,
            self.dependable_capacity_mw,
            self.peak_demand_mw,
        )
        if any(metric.low < 0 for metric in non_negative_ranges):
            raise ValueError("demand, generation, and capacity values cannot be negative")
        return self


class RegionalEnergyForecast(ContractModel):
    year: int = Field(ge=2026, le=2031)
    metrics: PowerBalanceMetrics
    method_id: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=100, allow_inf_nan=False)
    coverage: float = Field(ge=0, le=100, allow_inf_nan=False)
    value_kind: ValueKind

    @model_validator(mode="after")
    def provenance_is_present(self) -> "RegionalEnergyForecast":
        if not self.method_id.strip():
            raise ValueError("regional energy forecasts require a nonblank method ID")
        if not any(source_id.strip() for source_id in self.source_ids):
            raise ValueError("regional energy forecasts require at least one nonblank source ID")
        return self


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


class GeographyProperties(ContractModel):
    id: str
    name: str
    country: str = Field(min_length=2, max_length=2)
    level: GeographyLevel
    parent_id: str | None = None
    score_year: int = Field(ge=2026, le=2031)
    scores: LensScores
    confidence: float = Field(ge=0, le=100)
    coverage: float = Field(ge=0, le=100)
    value_kind: ValueKind
    updated_at: AwareDatetime
    contributions: list[ScoreContribution] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    population: int | None = Field(default=None, ge=0)

    @computed_field
    @property
    def peer_level(self) -> str:
        return self.level


class AssetProperties(ContractModel):
    id: str
    name: str
    geography_id: str
    category: AssetCategory
    subtype: AssetSubtype | None = None
    lifecycle: LifecycleState
    demand_mw: DemandRange | None = None
    technology: GenerationTechnology | None = None
    secondary_fuel: str | None = None
    capacity_mw: MetricRange | None = None
    dependable_capacity_mw: MetricRange | None = None
    annual_generation_gwh: MetricRange | None = None
    commissioning_year: int | None = Field(default=None, gt=0)
    retirement_year: int | None = Field(default=None, gt=0)
    plant_id: str | None = None
    unit_id: str | None = None
    target_year: int | None = Field(default=None, ge=2026, le=2031)
    location_precision: LocationPrecision
    value_kind: ValueKind
    source_ids: list[str] = Field(default_factory=list)
    operator: str | None = None
    source_type: SourceType = SourceType.OFFICIAL_VERIFIED
    source_url: HttpUrl | None = None
    external_ids: dict[str, str] = Field(default_factory=dict)
    last_observed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def generation_and_demand_are_valid(self) -> "AssetProperties":
        if self.demand_mw is not None and not self.source_ids:
            raise ValueError("demand-contributing assets require at least one source")
        generation_ranges = (
            self.capacity_mw,
            self.dependable_capacity_mw,
            self.annual_generation_gwh,
        )
        generation_fields = (
            self.technology,
            self.secondary_fuel,
            *generation_ranges,
            self.commissioning_year,
            self.retirement_year,
            self.plant_id,
            self.unit_id,
        )
        if self.category != AssetCategory.POWER_GENERATION:
            if self.subtype is None:
                raise ValueError("non-generation assets require a subtype")
            if any(value is not None for value in generation_fields):
                raise ValueError("non-generation assets cannot contain generation-only fields")
            return self
        if self.subtype is not None:
            raise ValueError("power-generation assets cannot contain an infrastructure subtype")
        if self.technology is None:
            raise ValueError("power-generation assets require a technology")
        if any(metric is not None and metric.low < 0 for metric in generation_ranges):
            raise ValueError("generation capacity and output cannot be negative")
        if (
            any(metric is not None for metric in generation_ranges)
            and self.value_kind in (ValueKind.REPORTED, ValueKind.ESTIMATED)
            and not any(source_id.strip() for source_id in self.source_ids)
        ):
            raise ValueError("reported or estimated generation metrics require at least one nonblank source ID")
        if (
            self.commissioning_year is not None
            and self.retirement_year is not None
            and self.retirement_year < self.commissioning_year
        ):
            raise ValueError("retirement year cannot precede commissioning year")
        return self


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
