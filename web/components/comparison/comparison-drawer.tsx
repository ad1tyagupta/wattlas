import type { LensKey, RegionalEnergyData, RegionFeature } from "@/lib/snapshot/types";

type Props = { regions: RegionFeature[]; lens: LensKey; year: number; regionalEnergy?: RegionalEnergyData; onClose: () => void; onRemove: (id: string) => void };

export function ComparisonDrawer({ regions, lens, year, regionalEnergy = {}, onClose, onRemove }: Props) {
  if (regions.length < 2) return null;
  return (
    <section className="comparison-drawer" aria-label="Region comparison">
      <div className="comparison-header"><div><small>Regional comparison · {year}</small><h2>{regions.length} regions aligned</h2></div><button type="button" onClick={onClose} aria-label="Close comparison">×</button></div>
      <div className="comparison-grid">
        {regions.map((region) => {
          const score = region.properties.scoresByYear[String(year)]?.[lens] ?? null;
          const energy = regionalEnergy[region.properties.id]?.find((row) => row.year === year);
          const format = (value: number) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
          const confidence = lens === "powerBalance" && energy ? energy.confidence : region.properties.confidence;
          const valueKind = lens === "powerBalance" && energy ? energy.valueKind.replace(/^./, (letter) => letter.toUpperCase()) : region.properties.valueKind;
          return <article key={region.properties.id}><button type="button" onClick={() => onRemove(region.properties.id)} aria-label={`Remove ${region.properties.name}`}>×</button><small>{region.properties.country} · {region.properties.id}</small><h3>{region.properties.name}</h3><div className="comparison-score">{score ?? "—"}<span>{score == null ? "Not rankable" : "Active lens"}</span></div><p>Confidence {format(confidence)}% · {valueKind}</p>{lens === "powerBalance" && <dl className="comparison-energy"><dt>Demand</dt><dd>{energy?.metrics ? `${format(energy.metrics.demandGwh.central)} GWh` : "Unavailable"}</dd><dt>Local generation gap</dt><dd>{energy?.metrics?.localGenerationGapGwh ? `${format(energy.metrics.localGenerationGapGwh.central)} GWh` : "Unavailable"}</dd><dt>Coverage</dt><dd>{energy?.metrics ? `${format(energy.powerBalance?.coverage ?? energy.coverage)}%` : "Unavailable"}</dd></dl>}</article>;
        })}
      </div>
    </section>
  );
}
