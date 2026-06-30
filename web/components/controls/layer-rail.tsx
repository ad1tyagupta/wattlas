import { GENERATOR_COLORS } from "@/lib/map/generator-colors";
import type { GenerationTechnology, LensKey } from "@/lib/snapshot/types";

const lenses: Array<{ id: LensKey; label: string; description: string }> = [
  { id: "infrastructureDemand", label: "Infrastructure Demand", description: "Primary opportunity signal" },
  { id: "siteAttractiveness", label: "Site Attractiveness", description: "Delivery and location conditions" },
  { id: "systemRisk", label: "System Risk", description: "Constraint and resilience exposure" },
  { id: "powerBalance", label: "Power Balance", description: "Demand versus dependable supply" },
];

export type InfrastructureVisibility = { dataCentres: boolean; water: boolean; generators: boolean };
type Props = {
  activeLens: LensKey; onChange: (lens: LensKey) => void;
  infrastructure?: InfrastructureVisibility; onInfrastructureChange?: (value: InfrastructureVisibility) => void;
  technologies?: ReadonlySet<GenerationTechnology>; onTechnologiesChange?: (value: Set<GenerationTechnology>) => void;
  lifecycles?: ReadonlySet<string>; onLifecyclesChange?: (value: Set<string>) => void;
};

const technologyLabels: Record<GenerationTechnology, string> = { solar: "Solar", wind: "Wind", hydro: "Hydro", nuclear: "Nuclear", gas: "Gas", coal: "Coal", oil: "Oil", biomass: "Biomass", geothermal: "Geothermal", other: "Other" };
const lifecycleGroups = {
  operational: { label: "Operational", states: ["operational"] },
  construction: { label: "Under construction", states: ["under_construction"] },
  planned: { label: "Planned", states: ["announced", "planning_filed", "permitted"] },
} as const;

export function LayerRail({ activeLens, onChange, infrastructure, onInfrastructureChange, technologies, onTechnologiesChange, lifecycles, onLifecyclesChange }: Props) {
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
      {infrastructure && onInfrastructureChange && <div className="rail-section infrastructure-controls">
        <p className="rail-heading">Infrastructure</p>
        {([['dataCentres', 'Data centres'], ['water', 'Water infrastructure'], ['generators', 'Power generators']] as const).map(([id, label]) => <button key={id} type="button" aria-label={label} aria-pressed={infrastructure[id]} onClick={() => onInfrastructureChange({ ...infrastructure, [id]: !infrastructure[id] })}>{label}</button>)}
        {infrastructure.generators && technologies && onTechnologiesChange && <div className="generator-filters" aria-label="Generator technology filters">
          {(Object.keys(technologyLabels) as GenerationTechnology[]).map((technology) => <button key={technology} type="button" aria-label={technologyLabels[technology]} aria-pressed={technologies.has(technology)} onClick={() => { const next = new Set(technologies); if (next.has(technology)) next.delete(technology); else next.add(technology); onTechnologiesChange(next); }}><span aria-hidden="true" className="generator-swatch" style={{ backgroundColor: GENERATOR_COLORS[technology] }} />{technologyLabels[technology]}</button>)}
        </div>}
        {infrastructure.generators && lifecycles && onLifecyclesChange && <div className="generator-filters" aria-label="Generator lifecycle filters">
          {(Object.entries(lifecycleGroups)).map(([id, group]) => { const pressed = group.states.every((state) => lifecycles.has(state)); return <button key={id} type="button" aria-label={group.label} aria-pressed={pressed} onClick={() => { const next = new Set(lifecycles); for (const state of group.states) { if (pressed) next.delete(state); else next.add(state); } onLifecyclesChange(next); }}>{group.label}</button>; })}
        </div>}
      </div>}
      <div className="rail-section map-legend">
        <p className="rail-heading">Score intensity</p>
        <div className={`legend-ramp ${activeLens}`} />
        <div className="legend-labels">
          <span>{activeLens === "powerBalance" ? "Comfortable margin" : "Low"}</span>
          <span>{activeLens === "powerBalance" ? "Severe pressure" : "High"}</span>
        </div>
        <p className="legend-note">
          {activeLens === "powerBalance"
            ? "Slate indicates broad balance or uncertainty. Unavailable regions remain selectable."
            : "Neutral regions are not yet rankable. They remain selectable."}
        </p>
      </div>
      <div className="rail-section coverage-key">
        <p className="rail-heading">Coverage</p>
        <p><span className="key-mark estimated" /> Provisional analyst estimate</p>
        <p><span className="key-mark unavailable" /> Insufficient public evidence</p>
      </div>
    </aside>
  );
}
