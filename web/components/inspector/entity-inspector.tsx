import { formatPopulation } from "@/lib/format";
import type { AssetFeature, GeographyFeature, LensKey, RegionFeature } from "@/lib/snapshot/types";

const lensLabels: Record<LensKey, string> = {
  infrastructureDemand: "Infrastructure Demand",
  siteAttractiveness: "Site Attractiveness",
  systemRisk: "System Risk",
  powerBalance: "Power Balance",
};

type Props = {
  geography: GeographyFeature | RegionFeature | null;
  asset: AssetFeature | null;
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

export function EntityInspector({ geography, asset, lens, year, onOpenEvidence, onAddComparison }: Props) {
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

  return (
    <aside className="region-inspector">
      <div className="inspector-kicker">Selected region · {properties.country}</div>
      <h1>{properties.name}</h1>
      <p className="region-meta">{properties.id} · {formatPopulation(properties.population)}</p>

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

      <section className="driver-section">
        <div className="section-heading"><span>Score drivers</span><small>visible arithmetic</small></div>
        {contributions.length ? contributions.map((item) => (
          <button className="driver-row" key={item.id} type="button" onClick={onOpenEvidence}>
            <span>{item.label}<small>{item.rawValue} {item.unit}</small></span>
            <span className="driver-bar"><i style={{ width: `${((item.points ?? 0) / item.maxPoints) * 100}%` }} /></span>
            <strong>{item.points ?? "—"}<small>/{item.maxPoints}</small></strong>
          </button>
        )) : <p className="empty-evidence">Public evidence does not yet support a defensible score for this region.</p>}
      </section>

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
