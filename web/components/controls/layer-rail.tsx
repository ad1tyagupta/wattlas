import type { LensKey } from "@/lib/snapshot/types";

const lenses: Array<{ id: LensKey; label: string; description: string }> = [
  { id: "infrastructureDemand", label: "Infrastructure Demand", description: "Primary opportunity signal" },
  { id: "siteAttractiveness", label: "Site Attractiveness", description: "Delivery and location conditions" },
  { id: "systemRisk", label: "System Risk", description: "Constraint and resilience exposure" },
  { id: "powerBalance", label: "Power Balance", description: "Demand versus dependable supply" },
];

type Props = { activeLens: LensKey; onChange: (lens: LensKey) => void };

export function LayerRail({ activeLens, onChange }: Props) {
  return (
    <aside className="layer-rail" aria-label="Map controls">
      <div className="rail-section">
        <p className="rail-heading">Analytical lens</p>
        <div className="lens-list">
          {lenses.map((lens, index) => (
            <button
              key={lens.id}
              className={activeLens === lens.id ? "lens-button active" : "lens-button"}
              onClick={() => onChange(lens.id)}
              type="button"
              aria-pressed={activeLens === lens.id}
              aria-label={lens.label}
            >
              <span className="lens-index">0{index + 1}</span>
              <span>
                <strong>{lens.label}</strong>
                <small>{lens.description}</small>
              </span>
            </button>
          ))}
        </div>
      </div>
      <div className="rail-section map-legend">
        <p className="rail-heading">Score intensity</p>
        <div className={`legend-ramp ${activeLens}`} />
        <div className="legend-labels"><span>Low</span><span>High</span></div>
        <p className="legend-note">Neutral regions are not yet rankable. They remain selectable.</p>
      </div>
      <div className="rail-section coverage-key">
        <p className="rail-heading">Coverage</p>
        <p><span className="key-mark estimated" /> Provisional analyst estimate</p>
        <p><span className="key-mark unavailable" /> Insufficient public evidence</p>
      </div>
    </aside>
  );
}
