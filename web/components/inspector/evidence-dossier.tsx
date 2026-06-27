import type { EvidenceData, RegionFeature } from "@/lib/snapshot/types";

type Props = { region: RegionFeature | null; evidence: EvidenceData; open: boolean; onClose: () => void };

export function EvidenceDossier({ region, evidence, open, onClose }: Props) {
  if (!open || !region) return null;
  const sources = evidence.sources.filter((source) => region.properties.sourceIds.includes(source.id));
  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="drawer evidence-drawer" onMouseDown={(event) => event.stopPropagation()} aria-label="Evidence dossier">
        <div className="drawer-header"><div><small>Evidence dossier</small><h2>{region.properties.name}</h2></div><button type="button" onClick={onClose} aria-label="Close evidence dossier">×</button></div>
        <p className="drawer-intro">Every score contribution is an analyst estimate tied to cited public signals. It is not an observed regional grid measurement.</p>
        <div className="evidence-rule"><span>Value kind</span><strong>{region.properties.valueKind}</strong><span>Model</span><strong>1.0.0</strong><span>Coverage</span><strong>{region.properties.coverage}%</strong></div>
        <h3>Public sources</h3>
        {sources.length ? sources.map((source) => (
          <a className="source-row" href={source.url} target="_blank" rel="noreferrer" key={source.id}>
            <span>Tier {source.tier}</span><strong>{source.name}</strong><small>{new Date(source.publishedAt).toLocaleDateString("en-GB")}</small>
          </a>
        )) : <p className="empty-evidence">No score sources are attached to this region yet.</p>}
      </aside>
    </div>
  );
}
