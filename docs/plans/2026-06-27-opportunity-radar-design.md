# Europe Opportunity Radar — approved design

**Date:** 2026-06-27  
**Status:** Approved for implementation planning  
**Product:** GRID//SCOPE (provisional wordmark)

## 1. Purpose

Build a private, browser-based, Europe-first Opportunity Radar using public data. It answers:

> Where will European data-centre growth create the largest energy-infrastructure demand, opportunity, or constraint from 2026 through 2031?

The first version is a useful analytical instrument for the project owner. A public product, scenario laboratory, and cinematic globe/briefing mode may follow after verification.

## 2. Validated product experience

The home surface is a fast 2D analytical map of Europe. Users can:

1. Scan regions using the primary Infrastructure Demand lens.
2. Switch to Site Attractiveness or System Risk without leaving the map.
3. Move the active year from 2026 through 2031.
4. Zoom from Europe to region, cluster, project, and relevant grid context.
5. Hover for a terse summary and click to lock a selection.
6. Inspect score contributions, confidence, update dates, and source provenance.
7. Open an evidence dossier while preserving map context.
8. Compare selected regions in a drawer.

The product uses the wording `daily refreshed`, not `live`.

## 3. Scoring model

Infrastructure Demand is calculated for each scoreable entity and year using fixed, versioned thresholds rather than Europe-relative percentiles:

- Compute-load pressure: 25%
- Connection scarcity: 25%
- Grid-reinforcement gap: 20%
- Firm and flexible supply gap: 20%
- Cooling and water stress: 10%

Every component exposes its raw observations, units, dates, normalization rule, weight, contribution, evidence, and model version. European rank is derived separately.

The supporting lenses use the same evidence graph but separate formulas:

- **Site Attractiveness:** connection feasibility, delivery readiness, power conditions, carbon context, fibre/land context, and cooling conditions.
- **System Risk:** adequacy, congestion, concentration, volatility, climate exposure, and delivery uncertainty.

Confidence never rescales the score. It is displayed beside it through coverage, source quality, freshness, and agreement.

## 4. Geography and entities

Geography is a graph rather than a single hierarchy:

- Administrative: country, NUTS 2, NUTS 3.
- Power system: bidding zone, TSO/DSO service area, grid node or corridor when public.
- Market: data-centre cluster, campus, site, and project phase.

Relationships include `located_in`, `served_by`, `part_of_cluster`, and `affects`. A zone-level observation inherited by a region is explicitly labelled `inherited`; it is never presented as a regional measurement.

Project phases have independent capacity, dates, and lifecycle histories. Lifecycle states are announced, planning filed, permitted, under construction, operational, paused, and cancelled. Lifecycle and evidence quality remain separate concepts.

## 5. Evidence model

The core records are Source, Evidence Item, Claim, Observation, Entity, Relationship, Score Run, Score Component, and Confidence Assessment.

Source tiers:

- Tier A: official regulator, system operator, statistical body, or planning filing.
- Tier B: operator or project-promoter primary publication.
- Tier C: reputable independent reporting or industry publication.
- Tier D: unverified discovery lead; never used directly in a score.

A single authoritative Tier A source may establish a fact. Material Tier B/C capacity or timing claims require corroboration where possible. Conflicting claims are retained and surfaced.

Values are classified as observed, reported, estimated, inherited, or unavailable. Missing is null, never zero. Insufficient weighted coverage produces `not yet rankable` rather than a misleading number.

## 6. Daily snapshot architecture

The implementation is snapshot-first:

```text
Public connectors
  → immutable raw captures
  → normalized observations and claims
  → validation and geographic joins
  → score and confidence runs
  → immutable versioned snapshot
  → browser map and evidence UI
```

### Pipeline

A Python pipeline runs daily around 04:00 Europe/Berlin. DuckDB stores local analytical tables and performs spatial/data-quality transformations. Raw responses are retained with retrieval time and checksum. Reprocessing is incremental where inputs have not changed.

### Published snapshot

The pipeline exports a manifest plus compressed, versioned GeoJSON/JSON artifacts for regions, projects, scores, source status, and evidence summaries. The web application reads only a fully validated snapshot. A failed build never replaces the previous successful snapshot.

### Web application

Next.js App Router provides the application shell, routes, and server boundary. MapLibre GL JS renders the map and data-driven layers. A typed snapshot adapter isolates UI components from storage so a later PostGIS/API backend can replace static artifacts without rewriting the map.

## 7. Minimum connectors

The first implementation includes:

- GISCO NUTS boundaries and crosswalks.
- Eurostat REST/SDMX regional and energy context where directly applicable.
- ENTSO-E Transparency connector, enabled when an API token is configured.
- ENTSO-E TYNDP transmission/storage project portfolio ingestion.
- Capacitypedia/national TSO-DSO link registry with explicit coverage metadata.
- ERA5-derived historical climate-stress aggregates when credentials and download windows are configured.
- EU data-centre reporting aggregates.
- A curated, claim-level project registry sourced from planning filings, operator publications, and credible reporting.

Connectors may be current, cached, stale, failed, or not configured. The application remains usable from the last-known-good snapshot.

## 8. Launch coverage

All available European NUTS 2 regions and electricity bidding zones are selectable. Detailed project/evidence coverage begins with Frankfurt Rhine-Main, Greater Dublin, Amsterdam/North Holland, Greater London, Île-de-France, Madrid, Milan/Lombardy, and Stockholm/Mälardalen.

The interface distinguishes Europe-wide baseline coverage from evidence-rich launch clusters. It does not imply uniform data depth.

## 9. Interface structure

- Command bar: provisional wordmark, geography, search, snapshot status, and active horizon.
- Layer rail: lens selection, layer toggles, lifecycle filters, evidence/confidence filters, and legend.
- Map canvas: choropleth, projects, grid context, hover, selection, and zoom-dependent detail.
- Inspector: score, trend, component contributions, confidence, expected infrastructure needs, sources, and dossier action.
- Timeline: active year, six-year trend, and change markers.
- Comparison drawer: two or more selected regions with aligned drivers and provenance.
- Data-status drawer: connector freshness, failures, coverage, and last successful update.

## 10. Visual system

The visual language is defined in `design/brand-spec.md`. It is a restrained, dark cartographic interface with mineral colors, IBM Plex typography, rectilinear panels, accessible contrast, and progressive information disclosure.

The design avoids Palantir branding and generic cyber-dashboard tropes. Motion is limited to purposeful map camera transitions, inspector reveals, and time interpolation.

## 11. Failure and uncertainty behavior

- Connector failure: retain the previous data and mark the source failed.
- Stale data: retain it with an age warning based on metric-specific thresholds.
- Schema change: reject the connector output before normalization and alert in the pipeline report.
- Missing data: preserve null and reduce coverage; never zero-fill.
- Conflicting data: retain all claims, select a documented working value, and reduce agreement confidence.
- Estimated data: label method/version and widen the displayed range.
- Large score movement: quarantine the affected entities for review before publishing.
- Corrupt/incomplete snapshot: fail publication atomically and continue serving the last successful version.

## 12. Verification strategy

- Unit tests for normalization, weights, scenario handling, and confidence calculations.
- Contract fixtures for every connector and schema-change failure tests.
- Geographic tests for CRS, containment, crosswalks, and inherited values.
- Data-quality tests for nulls, ranges, duplicates, lifecycle transitions, stale thresholds, and source references.
- Golden snapshot tests and human-readable diffs for changed scores.
- Component tests for lens, filters, timeline, inspector, and comparison behavior.
- Browser tests for map loading, region selection, evidence opening, and error states.
- Accessibility tests for keyboard operation, focus order, non-color status cues, and contrast.
- Visual regression checks at desktop and tablet breakpoints.

## 13. First working version

Included:

- Daily snapshot pipeline and status report.
- Europe map with selectable regions.
- Infrastructure Demand, Site Attractiveness, and System Risk layers where evidence allows.
- 2026–2031 timeline.
- Launch-cluster project points and lifecycle filters.
- Score explanations, confidence, freshness, and evidence summaries.
- Region comparison and data-status views.
- Last-known-good fallback.

Deferred:

- 3D globe and cinematic briefing.
- Scenario Laboratory controls.
- Automated alerts and collaborative watchlists.
- Private/internal Siemens Energy connectors.
- Public multi-user authentication and deployment hardening.

## 14. Success criteria

The first version succeeds when the project owner can open the product at any time, immediately see the latest successful daily snapshot, understand which sources updated or failed, move across Europe and 2026–2031, compare regions, and trace every displayed score to dated public evidence without encountering fabricated precision.
