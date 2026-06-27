import { formatPopulation } from "@/lib/format";
import type { LensKey, RegionFeature } from "@/lib/snapshot/types";

const lensLabels: Record<LensKey, string> = {
  infrastructureDemand: "Infrastructure Demand",
  siteAttractiveness: "Site Attractiveness",
  systemRisk: "System Risk",
};

type Props = {
  region: RegionFeature | null;
  lens: LensKey;
  year: number;
  onOpenEvidence: () => void;
  onAddComparison: () => void;
};

export function RegionInspector({ region, lens, year, onOpenEvidence, onAddComparison }: Props) {
  if (!region) {
    return <aside className="region-inspector empty"><p>Select a region to inspect its evidence.</p></aside>;
  }
  const properties = region.properties;
  const scores = properties.scoresByYear[String(year)] ?? properties.scores;
  const score = scores[lens];
  const contributions = properties.contributionsByYear[String(year)] ?? [];

  return (
    <aside className="region-inspector">
      <div className="inspector-kicker">Selected region · {properties.country}</div>
      <h1>{properties.name}</h1>
      <p className="region-meta">{properties.id} · {formatPopulation(properties.population)}</p>

      <div className="headline-score">
        <div>
          <span>{score ?? "—"}</span>
          <small>/ 100</small>
        </div>
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
            <span className="driver-bar"><i style={{ width: `${(item.points / item.maxPoints) * 100}%` }} /></span>
            <strong>{item.points}<small>/{item.maxPoints}</small></strong>
          </button>
        )) : <p className="empty-evidence">Public evidence does not yet support a defensible score for this region.</p>}
      </section>

      <section className="needs-section">
        <div className="section-heading"><span>Potential infrastructure needs</span></div>
        {score == null ? <p className="empty-evidence">Needs are withheld until the region is rankable.</p> : (
          <div className="need-list">
            <span>Grid reinforcement</span><span>Substations</span><span>Transformers</span><span>Flexible capacity</span><span>Storage</span>
          </div>
        )}
      </section>

      <div className="inspector-actions">
        <button type="button" className="primary-action" onClick={onOpenEvidence}>Open evidence dossier</button>
        <button type="button" className="secondary-action" onClick={onAddComparison}>Add to comparison</button>
      </div>
    </aside>
  );
}
