# Wattlas Global Expansion Design

**Approved:** 2026-06-27  
**Status:** Ready for implementation planning

## Purpose

Expand the Europe-first Opportunity Radar into **Wattlas**, a global, daily-refreshed map of electricity demand created by upcoming data centres and water infrastructure. The experience must remain useful to infrastructure professionals while being legible to an interested general audience.

Wattlas answers:

> Where will new data-centre and water infrastructure create the largest electricity demand, opportunity, or system constraint during 2026–2031?

The release remains public-data-only. Infrastructure Demand is the primary score. Site Attractiveness and System Risk remain supporting lenses.

## Approach

Use a tiered hybrid model:

1. Provide a comparable country-level baseline globally.
2. Replace inherited country estimates with native subnational scores where reliable regional data exists.
3. Plot individual projects as the highest-resolution evidence layer.
4. Distinguish observed, reported, estimated, inherited, and unavailable values.

This avoids the sparseness of an asset-only map and the false uniformity of a country-only map.

## Geography and map behavior

- Open on a fast global 2D map.
- Keep thick national borders visible at every zoom level.
- Use UN-recognized boundaries and terminology. Prefer UN SALB or equivalent UN geospatial sources; do not independently adjudicate disputed claims.
- Reveal thinner state, province, or regional boundaries at closer zoom levels.
- Show the combined Infrastructure Demand choropleth by default.
- Provide three principal map modes: Combined Infrastructure, Data Centres, and Water Infrastructure.
- Treat power generation, transmission, and grid conditions as optional context rather than another demand category.
- Use distinct project symbols for data centres and water assets. Marker size represents modelled electrical demand, not raw IT capacity or water throughput.
- On selection, open the most specific available geography or project. Clearly label a regional value inherited from its country and render it differently from a native regional score.
- Provide global search across countries, regions, cities, operators, and projects.

Country and subnational scores are labelled by peer level and are not presented as interchangeable ranks.

## Infrastructure scope

### Data centres

Include upcoming hyperscale, colocation, cloud, AI/HPC, and other electrically material facilities supported by public evidence. Existing facilities provide context but do not drive the 2026–2031 incremental-demand score.

Convert reported grid capacity directly where possible. Otherwise convert IT capacity to facility demand using a visible PUE assumption and expose low, central, and high estimates.

### Water infrastructure

Include desalination, wastewater treatment, water reuse, electrically material pipelines and pumping schemes, and reservoirs or storage projects with an identifiable electrical load.

Convert throughput and technology into electrical demand using transparent energy-intensity assumptions. A reservoir without a material electrical load may appear as context but contributes no demand. Hydropower generation and passive water storage remain power-supply or resource context; they are not counted as demand.

## Explainable scores

### Infrastructure Demand · 0–100

- **Projected load · 60 points:** modelled additional electrical demand expected during 2026–2031.
- **Delivery timing · 15 points:** more weight for operational-near-horizon, under-construction, committed, and near-term projects.
- **Local load shock · 25 points:** incremental demand relative to the existing local electricity system.

The combined mode adds the asset classes in electrical terms. It does not force a 50/50 category weighting. Category toggles recalculate the same model using only the selected infrastructure.

Every score exposes component arithmetic, raw inputs, unit conversions, scenario range, dates, and source provenance.

### Site Attractiveness

Keep separate from demand. It reflects market momentum, policy and permitting environment, infrastructure access, power availability, connectivity, and asset-specific suitability.

### System Risk

Keep separate from demand and attractiveness. It reflects grid strain, supply shortfall, resource constraints, delivery risk, and political or regulatory uncertainty.

The Opportunity Radar compares the three lenses without blending them into an opaque master score.

## Evidence, uncertainty, and confidence

Classify every value as:

- Observed
- Reported
- Estimated
- Inherited
- Unavailable

Calculate confidence separately using source quality, freshness, geographic precision, corroboration, and metric completeness. Low confidence must not reduce the demand estimate; it warns the user about uncertainty.

Use exact asset coordinates only when officially public. Otherwise use a clearly labelled city or regional centroid. Never imply exactness that the source does not provide.

## Source policy

Use the following hierarchy:

1. Governments, regulators, grid operators, utilities, and official company disclosures.
2. Reputable open datasets such as Global Energy Monitor, Ember, World Bank, WRI, and ENERWAT-GLOB.
3. Transparent Wattlas estimates derived from public inputs.

Commercial directories may aid discovery but must not be scraped or redistributed unless a future licence explicitly permits it.

Each canonical project retains all supporting sources, publication and extraction dates, lifecycle state, operator, capacity, units, coordinates, assumptions, and confidence metadata.

## Data architecture

Keep data processing separate from the Vercel frontend:

1. A scheduled GitHub workflow runs once daily.
2. Source-specific Python adapters capture immutable raw inputs.
3. DuckDB normalizes units, resolves identities, deduplicates announcements, assigns geographies, estimates loads, and calculates scores.
4. Validation gates publish a versioned global snapshot only after all critical checks pass.
5. Vercel serves compact JSON/GeoJSON and static boundary assets through its CDN.

Pipeline stages are:

`Raw source -> normalized record -> canonical asset -> geographic assignment -> load estimate -> score -> published snapshot`

Separate static boundary releases from changing project and score snapshots.

## Update safety and failure behavior

Validate schemas, required fields, units, coordinates, dates, duplicates, row-count changes, and unexpected score movements. Record connector freshness and failures.

If an update fails, continue serving the last validated snapshot. The interface says **daily refreshed**, shows the exact successful timestamp, reports delayed feeds, and never describes stale or batch data as live.

## Interface

Preserve the existing dark analytical visual language while making explanations accessible to non-specialists.

The primary workspace contains:

- Wattlas identity, global search, refresh status, and coverage summary.
- Combined, Data Centres, and Water Infrastructure controls.
- Global map with persistent legend and strong geographic hierarchy.
- Ranked country or regional opportunity panel.
- Inspector with score breakdown, projected MW range, asset pipeline, timeline, drivers, risks, confidence, and sources.
- Opportunity Radar comparing Infrastructure Demand, Site Attractiveness, and System Risk.
- Plain-language explanations alongside professional units and evidence.

The release is responsive for tablet and mobile, but the densest analytical workflow remains desktop-first. It does not include CSV downloads, authentication, private connectors, 3D globe mode, or scenario editing.

## Initial coverage

Provide global country coverage wherever the minimum comparable public inputs exist. Ingest all reliable subnational sources available, prioritizing:

- Europe
- United States and Canada
- China
- India
- Gulf markets
- Major Asia-Pacific economies

Countries without native subnational evidence retain country-level analysis and labelled inherited regional values. Missing evidence is null, never zero.

## Testing and acceptance

The implementation is acceptable when:

- The global map loads and national boundaries remain legible at all supported zooms.
- Country selection, regional drill-down, search, toggles, ranking, and inspector work across desktop and mobile.
- Combined scores equal the documented electrical-demand model and category toggles recompute consistently.
- Unit conversions and low/base/high demand scenarios have deterministic tests.
- Inherited, estimated, unavailable, and stale data are visually distinguishable.
- Every displayed project and score can reach its evidence and calculation trail.
- Failed connectors preserve the last-known-good snapshot.
- The production build is ready to connect to a future Wattlas GitHub repository and Vercel project.

## Deferred

- Production GitHub repository creation and Vercel deployment
- CSV or API exports
- User accounts, watchlists, and alerts
- Licensed commercial datasets
- Private company data connectors
- Interactive scenarios
- Cinematic 3D briefing mode
