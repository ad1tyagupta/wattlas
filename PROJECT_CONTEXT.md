# Palantir - My Ver

## Status

The Europe-first working vertical slice and the global Wattlas map were implemented on 2026-06-27. Global facility coverage was expanded the same day using community-maintained OpenStreetMap infrastructure merged with curated official project evidence. Global ADM1 state/province intelligence, the declared Government of India boundary perspective, and richer facility inspection were implemented on 2026-06-28.

## Origin

The project is inspired by Bilawal Sidhu's browser-based WorldView / “God's Eye View” geospatial command center:

- https://www.youtube.com/watch?v=7HEUCLc7aL8&t=312s
- https://www.youtube.com/watch?v=ccZzOGnT4Cg&t=810s
- https://www.youtube.com/watch?v=0p8o7AeHDzg
- https://www.youtube.com/watch?v=rXvU7bPJ8n4&t=124s

The inspiration includes a cinematic 3D globe, time-based playback, multiple public-data layers, evidence-backed event tracking, tactical visual modes, and public OSINT fusion. The goal is not to clone every military/OSINT feature. The product has been deliberately narrowed to a differentiated energy-intelligence use case.

## Validated product direction

Build a Europe-first, browser-based **energy and data-center infrastructure Opportunity Radar** using public data.

The product should answer:

> Where will European data-center growth create the largest energy-infrastructure demand, opportunity, or constraint over the next five years?

The long-term product should combine:

1. A useful public analytical platform.
2. A cinematic WorldView-style presentation and briefing mode.

The first version should be a private working instrument. It may later become public after verification.

### Approved global expansion

The original Europe-first scope remains the validated foundation and historical first release. The next release expands the Opportunity Radar globally while preserving the 2026–2031 horizon, public-data-only boundary, Infrastructure Demand primary score, and Site Attractiveness/System Risk supporting lenses.

- **Product name:** Wattlas.
- **Audience:** both infrastructure professionals (investors, developers, utilities, and energy planners) and an interested general public.
- **Geography:** global country coverage with thick national boundaries; progressively reveal subnational boundaries and scores where reliable public data exists.
- **Boundary policy:** use UN national geometry generally, geoBoundaries `gbOpen` ADM1 state/province geometry, and GISCO NUTS-2 for deeper European detail. India is the approved exception: its national and state/union-territory geometry uses the declared **Government of India perspective**, with explicit attribution rather than silently adjudicating disputed claims.
- **Infrastructure:** combine data centres and water infrastructure in one electrical-demand model, with toggles that isolate each category.
- **Water scope:** desalination, wastewater treatment, water reuse, electrically material pipelines/pumping, and reservoirs. Only documented or estimated electrical consumption contributes to demand; hydropower and passive storage remain supply/context layers.
- **Asset timing:** upcoming 2026–2031 projects drive the score; existing assets provide context.
- **Location precision:** use exact coordinates when officially public; otherwise show a labelled city or regional centroid. Never fabricate precision.
- **Subnational priority:** ingest every reliable region available, initially prioritizing Europe, the United States and Canada, China, India, Gulf markets, and major Asia-Pacific economies. Use clearly labelled inherited national estimates where regional data is absent.
- **Downloads:** map viewing and evidence inspection only in this release; no CSV export.
- **Publishing:** complete a local, GitHub/Vercel-ready build first. Repository creation and production deployment follow separately.

The approved global design is recorded in `docs/plans/2026-06-27-wattlas-global-expansion-design.md`.

### Approved global state power-balance expansion

The next approved release turns Wattlas into an evidence-first global ADM1 electricity-balance atlas while preserving every earlier product decision.

- **Regional visibility:** show first-order state/province-equivalent borders faintly from the world view, strengthen them with zoom, add labels at medium zoom, and retain deeper layers such as European NUTS-2 at closer zoom.
- **Regional population:** use official ADM1 population first and WorldPop Global2 estimates otherwise, with source year, confidence, and observed/estimated labels.
- **Power generation:** add utility-scale operating, construction, and planned plants as a third infrastructure category; exclude household and rooftop generators.
- **Generator technologies:** use individual colours for solar, wind, hydropower, nuclear, gas, coal, oil, biomass, geothermal, and other, reinforced by marker shape or outline.
- **Hybrid electricity balance:** use official ADM1 demand, generation, interchange, and shortage data where available; otherwise publish controlled low/base/high estimates tied to national totals and public spatial covariates.
- **Deficit terminology:** keep local generation gap, net balance, and officially observed unmet demand separate. Never call demand minus local generation a definitive shortage when imports are unknown.
- **Time:** show the latest actual data plus 2026–2031 demand, supply, capacity, and balance projections.
- **Power Balance lens:** add a fourth explainable analytical lens while retaining Infrastructure Demand as primary and Site Attractiveness/System Risk as supporting lenses.
- **Attribution:** add the subtle persistent line `Created by Aditya Gupta · Open-source project`, linking to the GitHub repository.
- **Quality posture:** every regional result exposes source, date, method, confidence, coverage, and value kind; unavailable data remains unavailable rather than zero.

The approved design is recorded in `docs/plans/2026-06-28-global-state-power-balance-design.md`.

## Decisions already approved

- **Initial user:** the project owner, who works at Siemens Energy.
- **Data boundary:** public data only for the first version. Authorized internal data may be connected later through separate, secure connectors.
- **Geography:** Europe first, while keeping the visual shell capable of becoming global.
- **Time horizon:** prioritize long-term opportunity over near-term operations, approximately 2026–2031 / one to five years.
- **Weather:** use weather and climate as a stress-test/context layer, not the primary product identity. Examples include heat-driven demand, cooling constraints, drought/water stress, and renewable-generation conditions.
- **Lead experience:** Opportunity Radar.
- **Primary score:** Energy Infrastructure Demand.
- **Supporting lenses:** Data-Center Site Attractiveness and Energy-System Risk.
- **Public-product posture:** vendor-neutral analytical language even though the private prototype is strategically relevant to Siemens Energy.
- **Scoring principle:** avoid a magical opaque number. Every score must expose its drivers, confidence, evidence, dates, and source provenance.
- **Refresh model:** run an incremental public-data update once per day, retain immutable snapshots, and keep serving the last successful snapshot if a connector fails.
- **Freshness language:** say **daily refreshed**, not “live”; show global and per-source timestamps and connector states.
- **Primary map experience:** a fast 2D Europe analytical canvas with progressive zoom, persistent regional inspection, and comparison. Preserve the 3D globe for later Cinematic Briefing mode.

## Product approaches considered

### A. Opportunity Radar — selected

Rank regions and announced projects using compute-capacity growth, grid headroom, connection scarcity, generation and storage pipelines, cooling conditions, infrastructure gaps, and evidence confidence.

### B. Scenario Laboratory — future capability

Let users vary data-center growth, weather, generation, and grid assumptions to explore supply-demand gaps through 2030.

### C. Cinematic Briefing — future public/presentation mode

Turn verified data into guided stories that move through regions, projects, constraints, timelines, and implications on the 3D globe.

Recommended sequence: build A first, design the data model so B is possible, then add C as the polished public-facing mode.

## Approved core experience

The core screen and interaction loop were approved:

1. Scan ranked European opportunity hotspots on a globe/map.
2. Switch among Infrastructure Demand, Site Attractiveness, and System Risk lenses.
3. Select a region or project.
4. Inspect a transparent score breakdown and the factors driving it.
5. Review confidence, source count, dates, provenance, and evidence.
6. Open a deeper evidence dossier.
7. Watch a region or create a cinematic briefing.

The selected-region panel should explain likely needs such as substations, transformers, flexible generation, storage, grid reinforcement, cooling, and related energy infrastructure without turning the public product into a company-specific sales tool.

## Early public-data findings

- ENTSO-E Transparency Platform: operational load, generation, transmission, and market-related grid data.
- ENTSO-E / DSO Entity Capacitypedia: a pan-European overview of available grid-hosting-capacity information, launched in May 2026.
- Copernicus / ECMWF ERA5 and related products: weather and climate variables, including temperature, wind, solar-related conditions, drought, and historical stress analysis.
- EU data-center energy-performance reporting: useful public aggregated statistics at Member State and Union level.
- EU Delegated Regulation 2024/1364: reporting applies to qualifying data centres, but public outputs are primarily aggregated.
- Eurostat and national datasets: regional energy, economic, demographic, building, and industrial context.
- Individual planned data-center sites are the difficult layer. They will require a curated pipeline from planning applications, company announcements, operator publications, and credible reporting. Every site record needs lifecycle status and evidence confidence.

Useful official sources:

- https://www.entsoe.eu/news/2026/05/22/entso-e-and-dso-entity-launched-capacitypedia-to-improve-access-to-grid-hosting-capacity-information-across-europe/
- https://climate.copernicus.eu/climate-reanalysis
- https://energy.ec.europa.eu/topics/energy-efficiency/energy-efficiency-targets-directive-and-rules/energy-efficiency-directive/energy-performance-data-centres_en
- https://eur-lex.europa.eu/eli/reg_del/2024/1364/oj?locale=eng

## Visual artifacts

The exploratory companion screens are preserved under `design/visual-companion/`:

- `product-approaches.html` — the three product approaches.
- `core-experience.html` — the approved Opportunity Radar core-screen concept.
- `scoring-data-model.html` — the approved explainable scoring and evidence model.
- `map-experience-approaches.html` — the approved map-first direction and alternatives.

These are design artifacts, not implementation code.

## Conversation archive

The complete source-thread event archive is preserved at:

- `archive/source-thread-full.jsonl`

This file contains the original prompts, responses, and tool-event history for exact reference. Use this context document for normal continuation and consult the archive only when exact wording is needed.

## Approved design and implementation

The complete design is recorded in:

- `docs/plans/2026-06-27-opportunity-radar-design.md`
- `design/brand-spec.md`
- `product-facts.md`

The implementation plan is recorded in `docs/superpowers/plans/2026-06-27-opportunity-radar-working-version.md`.

The working version now includes:

- A Next.js 16 / React 19 analytical shell using the approved Huashu visual system.
- A clustered global MapLibre map with 246 countries, 3,229 geoBoundaries ADM1 states/provinces across 197 countries, all 334 GISCO NUTS-2 regions, and thick national boundaries.
- Snapshot `2026-06-28T05-11-05Z` with 3,628 facilities: 3,527 data centres and 101 water-infrastructure assets.
- A zoom hierarchy that keeps national borders strongest, reveals global ADM1 boundaries at medium zoom, and reveals European NUTS-2 boundaries closer in.
- The Government of India perspective for India, validated to include all 36 states/union territories and specifically Jammu and Kashmir, Ladakh, Assam, and Arunachal Pradesh.
- QLever/OpenStreetMap ingestion with ODbL attribution, stable source links, community/official provenance, lifecycle, operator, and location-precision labels.
- Individual facility inspection grouped into Identity, Location, Operations, Energy, and Sources, with owner/operator, public address tags, references, dates, reported power, external IDs, precise coordinates, provenance, and honest unavailable states.
- Country, ADM1, and NUTS-2 summaries split by operational/planned, category, and official/community source.
- 2026–2031 Infrastructure Demand, Site Attractiveness, and System Risk views.
- Explicit score arithmetic, confidence, coverage, value kind, evidence dossiers, source state, and comparison.
- A Python 3.13 / DuckDB snapshot pipeline using UN Geodata, QLever/OpenStreetMap, GISCO, Eurostat, curated public evidence, and an optional ENTSO-E connector.
- Immutable published GeoJSON/JSON snapshots and a last-known-good connector fallback.
- An active local Codex refresh automation at 04:00 Europe/Berlin once per day.
- A GitHub Actions refresh alternative at approximately 04:00 Europe/Berlin once per day, with manual dispatch.

Production is Git-connected at `https://wattlas.vercel.app`. The daily pipeline keeps the version-pinned boundary artifact separate from frequently changing facility data, rejects partial OSM responses below the coverage threshold, retains the last known good capture on failure, and commits validated snapshot changes.
