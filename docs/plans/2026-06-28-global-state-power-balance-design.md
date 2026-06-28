# Wattlas Global State Power Balance Design

**Status:** Approved on 2026-06-28

## Objective

Turn Wattlas into an evidence-first global state/province electricity-balance atlas. Make first-order administrative boundaries legible and selectable worldwide, enrich each region with population and electricity-balance intelligence, add utility-scale power-generation facilities, and introduce a dedicated Power Balance lens without weakening the approved Opportunity Radar.

## Validated product constraints

- Wattlas remains global, public-data-only, daily refreshed, and evidence-first.
- Infrastructure Demand remains the primary opportunity score.
- Site Attractiveness and System Risk remain supporting lenses.
- Power Balance becomes a fourth analytical lens rather than replacing an existing lens.
- The analytical horizon remains 2026–2031.
- Official regional values take precedence; clearly labelled estimates fill defensible gaps.
- Missing data remains unavailable rather than being represented as zero.
- Community-maintained and officially verified records remain visibly distinct.
- The site includes the subtle persistent credit `Created by Aditya Gupta · Open-source project`, with the second phrase linked to the GitHub repository.

## Selected approach

Use an evidence-first hybrid model.

1. Ingest official ADM1 population, demand, generation, interchange, shortage, and plant data wherever reusable public sources exist.
2. Fill population gaps with WorldPop Global2 estimates.
3. Fill electricity-demand and local-generation gaps with controlled models tied to national totals, public covariates, and explicit uncertainty.
4. Keep local generation gap and officially observed unmet demand as separate metrics.
5. Publish source, date, method, confidence, and value kind for every regional result.

This approach provides global utility without presenting modelled values as measurements.

## Geographic hierarchy

Use one hierarchy:

1. World.
2. Country.
3. ADM1 first-order subdivision: state, province, governorate, emirate, department, region, or equivalent.
4. A deeper regional layer where a validated public source exists, such as European NUTS-2.

Use geoBoundaries `gbOpen` as the global ADM1 baseline, with redistributable official sources as overrides or gap-fillers. Preserve the approved Government of India perspective and its validation gate for all 36 states and union territories, including Jammu and Kashmir, Ladakh, Assam, and Arunachal Pradesh.

Do not invent subdivisions. Countries without a genuine or redistributable ADM1 layer, including applicable microstates and territories, remain country-level and display the reason.

## Boundary presentation

- Keep national borders thickest and brightest.
- Show ADM1 borders faintly from the initial world view rather than hiding them until medium zoom.
- Increase ADM1 contrast and width progressively with zoom.
- Add collision-aware ADM1 labels at medium zoom.
- Reveal deeper layers such as NUTS-2 only at closer zoom.
- Keep every available ADM1 region selectable even when its energy data is unavailable.
- Use geometry simplification and immutable boundary artifacts so the layer remains browser-safe.

## Regional population

Each region exposes a current population, source year, value kind, confidence, and optional 2026–2031 projection.

Source order:

1. Official census or statistical-office ADM1 result matching the active boundary.
2. WorldPop Global2 zonal aggregation for the active Wattlas geometry.
3. Unavailable when geometry or population coverage is not defensible.

WorldPop values are labelled modelled estimates even where their national total is aligned to UN World Population Prospects.

## Power-generation facilities

Add `power_generation` as a third infrastructure category alongside `data_centre` and `water_infrastructure`.

The initial scope includes utility-scale operating, construction, and planned facilities. Exclude individual rooftop and household-scale generators to protect usefulness and performance.

Primary source order:

1. Reusable official generator registries.
2. Global Energy Monitor Global Integrated Power Tracker.
3. WRI Global Power Plant Database where useful and current enough.
4. OpenStreetMap community mapping as a gap-filler.

Canonical plant fields include:

- stable Wattlas ID and external IDs;
- plant, project, phase, and unit relationships;
- name, owner, operator, source type, source URL, licence, and last-observed date;
- country, ADM1, coordinates, and location precision;
- technology, primary and secondary fuel, and renewable/fossil classification;
- lifecycle, start year, retirement year, and expected commissioning year;
- nameplate capacity MW;
- dependable capacity MW or low/base/high estimate;
- reported annual generation GWh where available;
- estimated annual generation range where reported generation is absent;
- confidence and value kind.

Canonicalization uses strong external IDs first, then conservative name/operator/location/capacity agreement. Unit records may roll up into a plant without discarding unit-level evidence.

## Generator technology taxonomy and colours

Use both colour and marker shape/outline.

- Solar: gold.
- Wind: cyan.
- Hydropower: blue.
- Nuclear: violet.
- Gas: orange.
- Coal: red-charcoal.
- Oil: brown.
- Biomass: green.
- Geothermal: magenta.
- Other or unresolved: grey.

Data centres remain periwinkle and desalination/water infrastructure remains mint. Mixed clusters use a neutral colour and expose their technology composition on selection; otherwise clusters use the dominant category or technology.

## Regional electricity data model

Each ADM1 record can expose:

- population and projected population;
- annual electricity demand/consumption GWh;
- peak demand MW;
- local net generation GWh;
- installed nameplate capacity MW;
- dependable capacity MW;
- generation and capacity mix by technology;
- imports, exports, and net interchange when reported;
- local generation gap GWh;
- dependable-capacity margin MW;
- officially observed unmet demand, energy not served, load shedding, or service deficit when reported;
- operating, construction, planned, and retiring generation capacity;
- explicit data-centre and water-infrastructure demand ranges;
- low/base/high 2026–2031 demand, supply, and balance projections;
- confidence, coverage, value kind, method ID, and source IDs.

### Terminology rule

Do not label demand minus local generation as a definitive power deficit. A region may import electricity. Use:

- `Local generation gap` for demand minus local generation before known interchange.
- `Net balance` when public import/export or interchange data are available.
- `Observed unmet demand` only for an official shortage, load-shedding, or energy-not-served measure.

## Hybrid demand and supply model

### Demand

Use official ADM1 sales, consumption, load, or peak-demand values first. Otherwise allocate a validated national electricity-demand control total across ADM1 regions using public covariates such as:

- population and population growth;
- gridded economic activity or GDP;
- nighttime lights;
- industrial and commercial facilities;
- heating and cooling conditions;
- urbanisation;
- explicit data-centre and water-infrastructure demand.

The model produces low/base/high values, not false point precision. Country adapters may override the generic allocation model where a better public method exists.

### Supply

Use reported regional or plant generation first. When only capacity is available, estimate annual generation with technology-, country-, and status-aware capacity-factor ranges. Estimate dependable capacity with technology-specific capacity-credit ranges rather than treating renewable nameplate capacity as continuously available.

Known imports and exports adjust the net balance. Unknown interchange remains unknown.

### Forecast

For 2026–2031:

- project population and baseline demand with cited national or regional outlooks where available;
- add explicit data-centre and water-infrastructure demand ranges;
- incorporate operating plants, planned commissioning, construction status, announced retirement, and delivery confidence;
- preserve low/base/high demand, supply, and balance paths;
- withhold rankable outputs when uncertainty exceeds an approved threshold.

## Power Balance lens

Add a 0–100 Power Balance pressure score, where higher means greater pressure or shortage exposure. It is a navigation aid; raw MW/GWh values remain primary in the inspector.

Initial weights:

- 35% dependable-capacity margin versus peak demand.
- 30% annual local generation versus demand.
- 15% officially observed unmet demand or load shedding.
- 10% projected 2026–2031 demand growth.
- 10% expected supply additions, retirements, and delivery confidence.

Re-normalize only across available components using the existing missing-data policy and show the effective denominator. Do not assign points for unavailable evidence. Every contribution exposes raw value, unit, normalization, points, maximum points, value kind, source IDs, and method version.

Power Balance map fill uses a diverging interpretation:

- teal for estimated surplus or comfortable margin;
- neutral slate for broad balance or material uncertainty;
- amber for moderate pressure;
- red for severe pressure or officially observed shortage;
- low-opacity or hatched styling for insufficient evidence.

Infrastructure Demand remains the primary score for opportunity ranking. Power Balance explains whether local supply appears able to meet the load outlook.

## Interaction design

Users can independently toggle:

- data centres;
- desalination/water facilities;
- power generators.

Generator filters include technology and lifecycle. The map retains clustering at world scale and reveals individual facilities progressively.

Selecting an ADM1 region opens a regional energy panel with:

1. Population and projected growth.
2. Current demand, peak load, generation, and dependable capacity.
3. Local generation gap, net balance when available, and observed unmet demand.
4. Generation mix.
5. Operating, construction, planned, and retiring plants.
6. Data-centre and water-infrastructure demand.
7. A 2026–2031 demand-versus-supply range chart.
8. Confidence, method, freshness, and direct public source links.

Selecting a generator opens the grouped facility inspector with its technology, fuel, capacity, generation, lifecycle, dates, ownership, coordinates, source, and confidence.

## Attribution

Keep dataset and cartographic attribution visible. Add the subtle persistent line:

`Created by Aditya Gupta · Open-source project`

Render it in existing small muted typography beside map/data attribution or in the same persistent attribution area. Link `Open-source project` to `https://github.com/ad1tyagupta/wattlas`. Keep accessible contrast and keyboard focus without competing with the analytical interface.

## Data flow and refresh

The browser remains snapshot-driven and never queries upstream sources directly.

1. Fetch or reuse public source captures.
2. Normalize source-specific regional statistics and generator records.
3. Canonicalize plants and validate source licences.
4. Spatially assign facilities and gridded values to the active ADM1 geometry.
5. Calculate observed and modelled population, demand, supply, interchange, and forecast ranges.
6. Calculate explainable scores and regional summaries.
7. Validate coverage, arithmetic, geometry, source lineage, and artifact size.
8. Atomically publish immutable artifacts and update `latest.json`.

The orchestration runs daily, but source observations retain their actual cadence. Static boundaries, annual population, monthly operations, and rolling plant trackers are not mislabelled as daily measurements merely because Wattlas checked them that day.

## Failure handling and quality gates

- Retain last-known-good captures and snapshots on connector failure.
- Reject unexpected country, ADM1, plant, population, or demand coverage drops.
- Reject duplicate IDs, invalid geometry, impossible coordinates, negative capacity, invalid lifecycle transitions, and inconsistent units.
- Reject regional totals outside configured tolerance of their controlling country totals.
- Reject supply estimates that use nameplate capacity as dependable capacity without an approved method.
- Never convert missing data to zero.
- Mark stale, inherited, modelled, and unavailable values explicitly.
- Keep regions selectable when unrankable.
- Expose source-specific status and last-success dates.

## Performance

- Keep boundary geometry in a separately cacheable immutable artifact.
- Load heavy ADM1 and generator artifacts client-side rather than serializing them into the initial HTML.
- Add category-specific or tiled artifacts if a single GeoJSON exceeds browser-safe limits.
- Cluster facilities and reduce marker density by zoom.
- Precompute regional summaries; do not aggregate hundreds of thousands of generator records in the browser.
- Enforce artifact-size, feature-count, and load-time budgets in CI.

## Verification

Automated verification must cover:

- boundary visibility at initial, medium, and close zoom;
- ADM1 coverage, labels, selection, and no fabricated microstate divisions;
- population aggregation and official-over-model precedence;
- generator source parsing, technology mapping, unit/plant canonicalization, and lifecycle;
- point-to-ADM1 assignment;
- reported generation and estimated capacity-factor arithmetic;
- dependable capacity and capacity-credit arithmetic;
- demand allocation reconciliation to country totals;
- separation of local generation gap, net balance, and observed unmet demand;
- 2026–2031 low/base/high forecast propagation;
- Power Balance contribution arithmetic and missing-data denominator;
- technology colours, colour-blind marker differentiation, clusters, filters, and selection;
- regional and generator inspectors;
- creator credit visibility and GitHub link;
- desktop, in-app pane, and mobile layout;
- snapshot checksums, last-known-good fallback, and coverage guards;
- production asset counts, browser console health, and Vercel deployment.

## Non-goals for this release

- Household and rooftop generator mapping.
- Real-time dispatch or grid-control operations.
- Claiming true shortages where imports or unmet-demand evidence are unknown.
- Power-flow modelling across transmission networks.
- Proprietary or internal datasets.
- Replacing the existing Opportunity Radar scores.

