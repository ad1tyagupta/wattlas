import type { LensKey, RegionFeature } from "@/lib/snapshot/types";

type Props = { regions: RegionFeature[]; lens: LensKey; year: number; onClose: () => void; onRemove: (id: string) => void };

export function ComparisonDrawer({ regions, lens, year, onClose, onRemove }: Props) {
  if (regions.length < 2) return null;
  return (
    <section className="comparison-drawer" aria-label="Region comparison">
      <div className="comparison-header"><div><small>Regional comparison · {year}</small><h2>{regions.length} regions aligned</h2></div><button type="button" onClick={onClose} aria-label="Close comparison">×</button></div>
      <div className="comparison-grid">
        {regions.map((region) => {
          const score = region.properties.scoresByYear[String(year)]?.[lens] ?? null;
          return <article key={region.properties.id}><button type="button" onClick={() => onRemove(region.properties.id)} aria-label={`Remove ${region.properties.name}`}>×</button><small>{region.properties.country} · {region.properties.id}</small><h3>{region.properties.name}</h3><div className="comparison-score">{score ?? "—"}<span>{score == null ? "Not rankable" : "Active lens"}</span></div><p>Confidence {region.properties.confidence}% · {region.properties.valueKind}</p></article>;
        })}
      </div>
    </section>
  );
}
