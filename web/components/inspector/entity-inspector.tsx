import { formatPopulation } from "@/lib/format";
import { PowerBalanceChart } from "@/components/inspector/power-balance-chart";
import type { AssetFeature, EvidenceData, GeneratorFeature, GeneratorOverviewCollection, GeographyFeature, LensKey, RegionalEnergyForecast, RegionalEnergyRow, RegionFeature } from "@/lib/snapshot/types";

const lensLabels: Record<LensKey, string> = {
  infrastructureDemand: "Infrastructure Demand",
  siteAttractiveness: "Site Attractiveness",
  systemRisk: "System Risk",
  powerBalance: "Power Balance",
};

type Props = {
  geography: GeographyFeature | RegionFeature | null;
  asset: AssetFeature | null;
  generator?: GeneratorFeature | null;
  regionalEnergy?: RegionalEnergyRow[];
  generatorOverview?: GeneratorOverviewCollection | null;
  evidence?: EvidenceData;
  regionalEnergyState?: "idle" | "loading" | "ready" | "error" | "unavailable";
  regionalEnergyError?: string | null;
  onRetryRegionalEnergy?: () => void;
  lens: LensKey;
  year: number;
  onOpenEvidence: () => void;
  onAddComparison: () => void;
};

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function formatObserved(value?: string | null): string {
  if (!value) return "Observation date unavailable";
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(value));
}

function formatAddress(address: AssetFeature["properties"]["address"]): string {
  if (!address) return "Full address unavailable";
  const street = [address.houseNumber, address.street].filter(Boolean).join(" ");
  return [street, address.city, address.state, address.postcode, address.country].filter(Boolean).join(", ") || "Full address unavailable";
}

function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? value : null;
  } catch { return null; }
}

const number = (value: number) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
const metric = (value: { central: number } | null, unit: string) => value ? `${number(value.central)} ${unit}` : "Unavailable";

export function EntityInspector({ geography, asset, generator, regionalEnergy = [], generatorOverview, evidence, regionalEnergyState = "ready", regionalEnergyError, onRetryRegionalEnergy, lens, year, onOpenEvidence, onAddComparison }: Props) {
  if (generator) {
    const properties = generator.properties;
    const name = typeof properties.name === "string" ? properties.name : properties.id;
    const sourceUrl = safeHttpUrl(properties.sourceUrl);
    return <aside className="region-inspector facility-inspector generator-inspector">
      <div className="inspector-kicker">Selected power generator · {properties.country}</div>
      <h1>{name}</h1>
      <p className="region-meta">{properties.technologies.map(humanize).join(" · ")}</p>
      <div className="facility-detail-groups">
        <section className="facility-detail-group"><h2>Plant</h2><div className="facility-facts">
          <span>Technology<strong>{properties.technologies.length ? properties.technologies.map(humanize).join(", ") : "Unavailable"}</strong></span>
          <span>Primary fuel<strong>{properties.primaryFuel || "Primary fuel unavailable"}</strong></span>
          <span>Secondary fuel<strong>{properties.secondaryFuel || "Secondary fuel unavailable"}</strong></span>
          <span>Capacity<strong>{number(properties.capacityMw)} MW</strong></span>
          <span>Annual generation<strong>{properties.annualGenerationGwh ? `${number(properties.annualGenerationGwh.central)} GWh (${number(properties.annualGenerationGwh.low)}–${number(properties.annualGenerationGwh.high)})` : "Generation unavailable"}</strong></span>
          <span>Status<strong>{properties.lifecycle ? humanize(properties.lifecycle) : "Status unavailable"}</strong></span>
        </div></section>
        <section className="facility-detail-group"><h2>Dates and ownership</h2><div className="facility-facts">
          <span>Commissioned<strong>{properties.commissioningYear ?? "Commissioning date unavailable"}</strong></span>
          <span>Retirement<strong>{properties.retirementYear ?? "Retirement date unavailable"}</strong></span>
          <span>Operator<strong>{typeof properties.operator === "string" ? properties.operator : "Operator unavailable"}</strong></span>
          <span>Owner<strong>{typeof properties.owner === "string" ? properties.owner : "Owner unavailable"}</strong></span>
        </div></section>
        <section className="facility-detail-group"><h2>Location and evidence</h2><div className="facility-facts">
          <span>Region<strong>{properties.geographyId}</strong></span><span>Coordinates<strong>{generator.geometry.coordinates[1].toFixed(5)}, {generator.geometry.coordinates[0].toFixed(5)}</strong></span>
          <span>Confidence<strong>{typeof properties.confidence === "number" ? `${properties.confidence}%` : "Confidence unavailable"}</strong></span>
          <span>Source IDs<strong>{properties.sourceIds.length ? properties.sourceIds.join(", ") : "Source IDs unavailable"}</strong></span>
        </div></section>
      </div>
      <div className="inspector-actions single-action">{sourceUrl ? <a className="primary-action" href={sourceUrl} target="_blank" rel="noreferrer">Open source record</a> : <button className="secondary-action" type="button" disabled>Source record unavailable</button>}</div>
    </aside>;
  }
  if (asset) {
    const properties = asset.properties;
    return (
      <aside className="region-inspector facility-inspector">
        <div className="inspector-kicker">Selected facility · {properties.country}</div>
        <h1>{properties.name}</h1>
        <p className="region-meta">{properties.operator || "Operator unavailable"}</p>
        <div className="facility-detail-groups">
          <section className="facility-detail-group"><h2>Identity</h2><div className="facility-facts">
            <span>Operator<strong>{properties.operator || "Unavailable"}</strong></span>
            <span>Owner<strong>{properties.owner || "Unavailable"}</strong></span>
            <span>Facility reference<strong>{properties.facilityRef || "Unavailable"}</strong></span>
            <span>Category<strong>{properties.category === "data_centre" ? "Data centre" : "Water infrastructure"}</strong></span>
          </div></section>
          <section className="facility-detail-group"><h2>Location</h2><div className="facility-facts">
            <span>Address<strong>{formatAddress(properties.address)}</strong></span>
            <span>Precision<strong>{humanize(properties.locationPrecision)}</strong></span>
            <span>Coordinates<strong>{asset.geometry.coordinates[1].toFixed(5)}, {asset.geometry.coordinates[0].toFixed(5)}</strong></span>
            <span>Region<strong>{properties.geographyId}</strong></span>
          </div></section>
          <section className="facility-detail-group"><h2>Operations</h2><div className="facility-facts">
            <span>Lifecycle<strong>{humanize(properties.lifecycle)}</strong></span>
            <span>Start date<strong>{properties.startDate || "Unavailable"}</strong></span>
            <span>Opening date<strong>{properties.openingDate || "Unavailable"}</strong></span>
            <span>Last observed<strong>{formatObserved(properties.lastObservedAt)}</strong></span>
          </div></section>
          <section className="facility-detail-group"><h2>Energy</h2><div className="facility-facts">
            <span>Reported power<strong>{properties.reportedPower || "Not publicly available"}</strong></span>
            <span>Demand MW<strong>{properties.demandMw ? `${properties.demandMw.low}–${properties.demandMw.high} MW` : "Not publicly available"}</strong></span>
          </div></section>
          <section className="facility-detail-group"><h2>Sources</h2><div className="facility-facts">
            <span>Source type<strong>{properties.sourceType === "official_verified" ? "Officially verified" : "Community mapped"}</strong></span>
            <span>Public IDs<strong>{Object.entries(properties.externalIds).map(([key, value]) => `${key.toUpperCase()} ${value}`).join(" · ") || "Unavailable"}</strong></span>
          </div>
          <div className="facility-source-links">
            {properties.sourceUrl && <a href={properties.sourceUrl} target="_blank" rel="noreferrer">Source record</a>}
            {properties.website && <a href={properties.website} target="_blank" rel="noreferrer">Facility website</a>}
            {properties.externalIds.wikidata && <a href={`https://www.wikidata.org/wiki/${properties.externalIds.wikidata}`} target="_blank" rel="noreferrer">Wikidata</a>}
          </div></section>
        </div>
        <p className="facility-note">
          {properties.sourceType === "community_mapped"
            ? "Community-mapped location data provides infrastructure context and does not create future demand by itself."
            : "This project is tied to a curated public announcement or official record."}
        </p>
        <div className="inspector-actions single-action">
          {properties.sourceUrl
            ? <a className="primary-action" href={properties.sourceUrl} target="_blank" rel="noreferrer">Open source record</a>
            : <span className="empty-evidence">Source URL unavailable</span>}
        </div>
      </aside>
    );
  }

  if (!geography) {
    return <aside className="region-inspector empty"><p>Select a country, region, or facility to inspect its evidence.</p></aside>;
  }
  const properties = geography.properties;
  const scores = properties.scoresByYear[String(year)] ?? properties.scores;
  const score = scores[lens];
  const contributions = properties.contributionsByYear[String(year)] ?? [];
  const summary = "assetSummary" in properties ? properties.assetSummary : null;
  const activeEnergy = regionalEnergy.find((row) => row.year === year);
  const rankableEnergy = regionalEnergy.filter(
    (row): row is RegionalEnergyForecast => row.metrics !== null,
  );
  const overview = generatorOverview?.features.find((feature) => feature.properties.geographyId === properties.id)?.properties;
  const demand = "demandMwByYear" in properties ? properties.demandMwByYear[String(year)] : undefined;
  const energySources = evidence?.sources.filter((source) => activeEnergy?.sourceIds.includes(source.id)) ?? [];
  const mixTotal = overview ? Object.values(overview.technologyMixMw).reduce((sum, value) => sum + (value ?? 0), 0) : 0;

  return (
    <aside className="region-inspector">
      <div className="inspector-kicker">Selected region · {properties.country}</div>
      <h1>{properties.name}</h1>
      <p className="region-meta">{properties.id} · {formatPopulation(properties.population)}</p>

      {lens === "powerBalance" && <section className="power-balance-panel" aria-label="Regional power balance">
        <div className="population-context"><strong>{properties.population == null ? "Population unavailable" : `${number(properties.population / 1_000_000)} million residents`}</strong><span>Source year {properties.populationSourceYear ?? "unavailable"} · Forecast growth unavailable · {humanize(properties.populationValueKind ?? properties.valueKind)}</span></div>
        {regionalEnergyState === "loading" ? <p className="empty-evidence" role="status">Loading regional energy data…</p>
        : regionalEnergyState === "error" ? <div className="energy-load-error" role="alert"><p>Could not load regional energy data. {regionalEnergyError || "Please try again."}</p>{onRetryRegionalEnergy && <button type="button" className="secondary-action" onClick={onRetryRegionalEnergy}>Retry regional energy</button>}</div>
        : activeEnergy?.metrics === null ? <div className="empty-evidence" role="status"><p><strong>Country-level data only.</strong> ADM1 demand is unavailable because at least one active region lacks defensible population coverage, so Wattlas does not fabricate regional shares.</p><p>{activeEnergy.countryControl ? `Published national demand control: ${metric(activeEnergy.countryControl.demandGwh, "GWh")}.` : "A national demand control is not currently available."}</p></div>
        : activeEnergy ? <>
          <div className="energy-facts">
            <span>Current demand<strong>{metric(activeEnergy.metrics.demandGwh, "GWh")}</strong></span><span>Peak demand<strong>{metric(activeEnergy.metrics.peakDemandMw, "MW")}</strong></span>
            <span>Local generation<strong>{metric(activeEnergy.metrics.localGenerationGwh, "GWh")}</strong></span><span>Dependable capacity<strong>{metric(activeEnergy.metrics.dependableCapacityMw, "MW")}</strong></span>
            <span>Local generation gap<strong>{metric(activeEnergy.metrics.localGenerationGapGwh, "GWh")}</strong></span>
            {activeEnergy.metrics.netBalanceGwh && <span>Net balance<strong>{metric(activeEnergy.metrics.netBalanceGwh, "GWh")}</strong></span>}
            {activeEnergy.metrics.observedUnmetDemandGwh != null && <span>Observed unmet demand<strong>{number(activeEnergy.metrics.observedUnmetDemandGwh)} GWh reported</strong></span>}
          </div>
          <div className="forward-demand"><span>Data-centre forward demand<strong>{demand?.data_centre ? `${number(demand.data_centre.low)}–${number(demand.data_centre.high)} MW` : "Unavailable"}</strong></span><span>Water forward demand<strong>{demand?.water_infrastructure ? `${number(demand.water_infrastructure.low)}–${number(demand.water_infrastructure.high)} MW` : "Unavailable"}</strong></span></div>
          {overview && <div className="generation-context"><h2>Generation mix and plant lifecycle</h2><div>{Object.entries(overview.technologyMixMw).map(([technology, capacity]) => <span key={technology}>{humanize(technology)} {mixTotal ? Math.round((capacity ?? 0) / mixTotal * 100) : 0}%</span>)}</div><div>{Object.entries(overview.lifecycleCounts ?? {}).map(([status, count]) => <span key={status}>{count} {humanize(status).toLowerCase()}</span>)}</div></div>}
          <PowerBalanceChart forecasts={rankableEnergy} />
          <section className="power-contributions"><div className="section-heading"><span>Power Balance contributions</span><small>{activeEnergy.powerBalance?.coverage ?? activeEnergy.coverage}% coverage</small></div>
            <p className="contribution-summary">{activeEnergy.powerBalance?.status === "rankable" ? "Rankable" : "Not yet rankable"} at {activeEnergy.powerBalance?.coverage ?? activeEnergy.coverage}% coverage · {(activeEnergy.powerBalance?.contributions ?? []).reduce((sum, item) => sum + (item.points ?? 0), 0)} of {(activeEnergy.powerBalance?.contributions ?? []).reduce((sum, item) => sum + (item.points == null ? 0 : item.maxPoints), 0)} available points</p>
            {activeEnergy.powerBalance?.contributions.map((item) => <div className="power-contribution" key={item.id}><div><span>{item.label}</span><small>{item.rawValue == null ? "Raw value unavailable" : `${number(item.rawValue)}${item.unit ? ` ${item.unit}` : ""}`}</small><small>{item.normalization}</small><small>{humanize(item.valueKind)} · {item.methodVersion}</small><small>Sources: {item.sourceIds.length ? item.sourceIds.join(", ") : "unavailable"}</small></div><strong>{item.points == null ? `Unavailable/${item.maxPoints} points` : `${item.points}/${item.maxPoints} points`}</strong></div>)}</section>
          <p className="method-note">Method: {activeEnergy.methodId}. Values marked estimated are modelled ranges, not reported measurements.</p>
          <div className="facility-source-links">{energySources.map((source) => <a key={source.id} href={source.url} target="_blank" rel="noreferrer">{source.name}</a>)}</div>
        </> : <p className="empty-evidence" role="status">Regional energy estimates are unavailable for this year.</p>}
      </section>}

      {summary && summary.total > 0 && (
        <section className="facility-summary" aria-label="Facility coverage">
          <strong>{summary.total} facilities</strong>
          <div>
            <span>{summary.operational} operational</span><span>{summary.planned} planned</span>
            <span>{summary.dataCentres} data centres</span><span>{summary.waterInfrastructure} water assets</span>
            <span>{summary.officialVerified} officially verified</span><span>{summary.communityMapped} community mapped</span>
          </div>
        </section>
      )}

      <div className="headline-score">
        <div><span>{score ?? "—"}</span><small>/ 100</small></div>
        <p>{score == null ? "Not yet rankable" : lensLabels[lens]}<small>{year} model view</small></p>
      </div>

      <div className="confidence-strip">
        <span>Confidence <strong>{properties.confidence}%</strong></span>
        <span>Coverage <strong>{properties.coverage}%</strong></span>
        <span className={`value-kind ${properties.valueKind}`}>{properties.valueKind}</span>
      </div>

      {lens !== "powerBalance" && <section className="driver-section">
        <div className="section-heading"><span>Score drivers</span><small>visible arithmetic</small></div>
        {contributions.length ? contributions.map((item) => (
          <button className="driver-row" key={item.id} type="button" onClick={onOpenEvidence}>
            <span>{item.label}<small>{item.rawValue} {item.unit}</small></span>
            <span className="driver-bar"><i style={{ width: `${((item.points ?? 0) / item.maxPoints) * 100}%` }} /></span>
            <strong>{item.points ?? "—"}<small>/{item.maxPoints}</small></strong>
          </button>
        )) : <p className="empty-evidence">Public evidence does not yet support a defensible score for this region.</p>}
      </section>}

      <section className="needs-section">
        <div className="section-heading"><span>Potential infrastructure needs</span></div>
        {score == null ? <p className="empty-evidence">Needs are withheld until the region is rankable.</p> : (
          <div className="need-list"><span>Grid reinforcement</span><span>Substations</span><span>Transformers</span><span>Flexible capacity</span><span>Storage</span></div>
        )}
      </section>

      <div className="inspector-actions">
        <button type="button" className="primary-action" onClick={onOpenEvidence}>Open evidence dossier</button>
        <button type="button" className="secondary-action" onClick={onAddComparison}>Add to comparison</button>
      </div>
    </aside>
  );
}
