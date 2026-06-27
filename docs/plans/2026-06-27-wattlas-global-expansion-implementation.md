# Wattlas Global Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the Europe-first GRID//SCOPE vertical slice into Wattlas, a deployment-ready global Opportunity Radar for 2026–2031 electricity demand from data centres and broad water infrastructure.

**Architecture:** Keep the Next.js/MapLibre frontend as a read-only consumer of versioned snapshots. Expand the Python/DuckDB pipeline into source adapters, canonical geography and asset records, transparent load conversion, peer-level scores, validation, and last-known-good publication. Use UN Geodata for the global national boundary layer and UN SALB only where authoritative subnational geometry is available; never synthesize disputed geometry.

**Tech Stack:** Python 3.13, Pydantic 2, DuckDB, httpx, pytest, Next.js 16, React 19, TypeScript, MapLibre GL 5, Zod 4, Vitest, Testing Library, Playwright, GitHub Actions, Vercel.

---

## Delivery rules

- Follow TDD for domain logic and UI behavior.
- Commit after every task.
- Keep missing data as `null`; never coerce it to zero.
- Retain immutable source references and calculation inputs.
- Show batch data as “daily refreshed,” never “live.”
- Do not scrape or redistribute commercial directories.
- Do not ship a project without a public source and an explicit precision classification.
- Run the full Python and web test suites before visual QA.

### Task 1: Rename the product and introduce global domain contracts

**Files:**
- Modify: `pipeline/src/grid_scope/models.py`
- Modify: `pipeline/tests/test_models.py`
- Modify: `web/lib/snapshot/types.ts`
- Modify: `web/lib/snapshot/schema.ts`
- Modify: `web/tests/snapshot.test.ts`
- Modify: `web/app/layout.tsx`
- Modify: `README.md`
- Modify: `web/README.md`

**Step 1: Write failing Python contract tests**

Add tests proving that:

```python
def test_asset_supports_data_centre_and_water_subtypes():
    asset = AssetProperties(
        id="asset-ae-desal-1",
        name="Example plant",
        geography_id="AE",
        category="water_infrastructure",
        subtype="desalination",
        lifecycle="under_construction",
        demand_mw={"low": 42, "central": 50, "high": 61},
        location_precision="city_centroid",
        value_kind="estimated",
        source_ids=["source-1"],
    )
    assert asset.category == "water_infrastructure"


def test_geography_has_country_and_peer_level():
    geography = GeographyProperties(..., level="country", parent_id=None)
    assert geography.peer_level == "country"
```

Cover data centre, desalination, wastewater, reuse, pipeline/pumping, reservoir/storage, and context-only assets. Reject negative demand and a demand-contributing asset without sources.

**Step 2: Run tests and verify failure**

Run: `cd pipeline && python -m pytest tests/test_models.py -q`  
Expected: FAIL because `AssetProperties`, global geography levels, demand ranges, and precision enums do not exist.

**Step 3: Implement the contracts**

Add enums and Pydantic models for:

```python
class GeographyLevel(StrEnum):
    COUNTRY = "country"
    ADMIN_1 = "admin_1"
    ADMIN_2 = "admin_2"

class AssetCategory(StrEnum):
    DATA_CENTRE = "data_centre"
    WATER_INFRASTRUCTURE = "water_infrastructure"

class LocationPrecision(StrEnum):
    EXACT = "exact"
    CITY_CENTROID = "city_centroid"
    REGION_CENTROID = "region_centroid"

class DemandRange(ContractModel):
    low: float = Field(ge=0)
    central: float = Field(ge=0)
    high: float = Field(ge=0)
```

Replace region-only and cluster-only assumptions with `GeographyProperties` and `AssetProperties`. Preserve compatibility aliases only where needed during the migration. Mirror the final JSON contract in Zod and TypeScript. Rename metadata and documentation to Wattlas.

**Step 4: Run contract tests**

Run: `cd pipeline && python -m pytest tests/test_models.py -q && cd ../web && npm test -- snapshot.test.ts`  
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/models.py pipeline/tests/test_models.py web/lib/snapshot web/tests/snapshot.test.ts web/app/layout.tsx README.md web/README.md
git commit -m "refactor: add Wattlas global data contracts"
```

### Task 2: Build transparent electrical-demand conversions

**Files:**
- Create: `pipeline/src/grid_scope/demand.py`
- Create: `pipeline/tests/test_demand.py`

**Step 1: Write failing conversion tests**

Cover:

```python
def test_it_capacity_uses_pue_range():
    result = data_centre_demand(it_capacity_mw=100, reported_grid_mw=None)
    assert result.central == 130
    assert result.low < result.central < result.high


def test_desalination_uses_throughput_and_energy_intensity():
    result = water_demand(
        subtype="desalination",
        throughput_m3_day=500_000,
        intensity_kwh_m3=ScenarioRange(low=2.8, central=3.5, high=4.2),
    )
    assert result.central == pytest.approx(72.9167, rel=1e-3)


def test_passive_reservoir_has_no_demand_without_pumping():
    assert water_demand(subtype="reservoir", throughput_m3_day=None, intensity_kwh_m3=None) is None
```

Also test direct grid MW precedence, wastewater, reuse, pipelines/pumping, unit conversion, bound ordering, and invalid inputs.

**Step 2: Verify failure**

Run: `cd pipeline && python -m pytest tests/test_demand.py -q`  
Expected: FAIL because the module does not exist.

**Step 3: Implement minimal deterministic converters**

Use documented defaults stored as named, versioned assumptions. Formula for flow-driven assets:

```python
mw = throughput_m3_day * intensity_kwh_m3 / 24_000
```

Return low/central/high MW plus the assumption identifier and input lineage. Do not infer a contribution for passive storage or hydropower generation.

**Step 4: Verify tests**

Run: `cd pipeline && python -m pytest tests/test_demand.py -q`  
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/demand.py pipeline/tests/test_demand.py
git commit -m "feat: model infrastructure electricity demand"
```

### Task 3: Replace the Europe score with the approved global score

**Files:**
- Modify: `pipeline/src/grid_scope/scoring.py`
- Modify: `pipeline/tests/test_scoring.py`
- Modify: `pipeline/src/grid_scope/snapshot_builder.py`
- Modify: `pipeline/tests/test_snapshot_builder.py`

**Step 1: Write failing score tests**

Test the approved weights and category behavior:

```python
def test_infrastructure_demand_weights_sum_to_100():
    result = score_infrastructure_demand(
        projected_load_index=80,
        delivery_timing_index=60,
        local_load_shock_index=40,
    )
    assert result.score == 67  # 48 + 9 + 10


def test_combined_load_sums_mw_not_category_scores():
    combined = combine_asset_demand(data_centre_mw=900, water_mw=100)
    assert combined == 1000
```

Test the 60/15/25 weights, fixed normalization bands, lifecycle timing weights, peer-level labels, confidence independence, inherited values, and non-rankable incomplete records.

**Step 2: Verify failure**

Run: `cd pipeline && python -m pytest tests/test_scoring.py tests/test_snapshot_builder.py -q`  
Expected: FAIL against the old five-driver Europe score.

**Step 3: Implement score model version 2**

Implement contributions named `projected_load`, `delivery_timing`, and `local_load_shock`. Keep Site Attractiveness and System Risk separate. Produce combined, data-centre-only, and water-only scores from the same underlying MW records. Keep confidence and coverage alongside, never inside, the arithmetic.

**Step 4: Verify tests**

Run: `cd pipeline && python -m pytest tests/test_scoring.py tests/test_snapshot_builder.py -q`  
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/scoring.py pipeline/src/grid_scope/snapshot_builder.py pipeline/tests/test_scoring.py pipeline/tests/test_snapshot_builder.py
git commit -m "feat: add explainable global demand scoring"
```

### Task 4: Ingest UN global national boundaries and available SALB regions

**Files:**
- Create: `pipeline/src/grid_scope/connectors/un_geodata.py`
- Create: `pipeline/src/grid_scope/connectors/un_salb.py`
- Create: `pipeline/tests/fixtures/un-geodata-sample.geojson`
- Create: `pipeline/tests/fixtures/un-salb-sample.geojson`
- Modify: `pipeline/tests/test_connectors.py`
- Modify: `pipeline/src/grid_scope/config.py`

**Step 1: Write failing connector tests**

Assert that the UN Geodata simplified country polygons normalize to stable M49/ISO identifiers and that SALB admin units retain parent relationships. Assert that the UN disclaimer is included in snapshot metadata. Reject geometry without an identifiable country.

**Step 2: Verify failure**

Run: `cd pipeline && python -m pytest tests/test_connectors.py -k 'un_geodata or un_salb' -q`  
Expected: FAIL because the adapters do not exist.

**Step 3: Implement adapters**

Use the official UN Geodata simplified GeoJSON item for national polygons and lines. Use SALB GeoJSON/REST resources only for countries with published validated subnational data. Cache raw responses immutably and keep connector-level last-known-good fallback. Do not substitute another boundary authority when SALB has no subnational geometry; omit that regional geometry and retain country analysis.

**Step 4: Verify tests**

Run: `cd pipeline && python -m pytest tests/test_connectors.py -q`  
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/connectors pipeline/src/grid_scope/config.py pipeline/tests
git commit -m "feat: ingest UN global boundaries"
```

### Task 5: Add global context connectors and a source-backed asset registry

**Files:**
- Create: `pipeline/src/grid_scope/connectors/world_bank.py`
- Create: `pipeline/src/grid_scope/connectors/ember.py`
- Create: `pipeline/src/grid_scope/connectors/global_assets.py`
- Create: `data/curated/global-assets.json`
- Create: `data/curated/source-registry.json`
- Modify: `pipeline/tests/test_connectors.py`

**Step 1: Write failing adapter and provenance tests**

Test World Bank pagination and nulls, Ember country matching, asset type normalization, lifecycle mapping, source tiers, precision labels, and rejection of an asset without a public URL. Use HTTP fixtures; tests must not depend on the network.

**Step 2: Verify failure**

Run: `cd pipeline && python -m pytest tests/test_connectors.py -k 'world_bank or ember or global_assets' -q`  
Expected: FAIL.

**Step 3: Implement source adapters and registry validation**

The first registry must cover every world region and emphasize the approved priority markets. Include only publicly evidenced 2026–2031 data-centre, desalination, wastewater, reuse, pipeline/pumping, and electrically material reservoir projects. Record all conversions and avoid commercial-directory content. Use official operators, regulators, ministries, public planning records, GEM/WRI/ENERWAT-GLOB, and other redistributable sources according to the design hierarchy.

**Step 4: Run tests and registry audit**

Run: `cd pipeline && python -m pytest tests/test_connectors.py -q`  
Expected: PASS, with every demand-contributing asset linked to at least one public source.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/connectors data/curated pipeline/tests/test_connectors.py
git commit -m "feat: add global infrastructure sources"
```

### Task 6: Canonicalize, deduplicate, and spatially assign assets

**Files:**
- Create: `pipeline/src/grid_scope/canonicalize.py`
- Create: `pipeline/tests/test_canonicalize.py`
- Modify: `pipeline/src/grid_scope/storage.py`

**Step 1: Write failing identity tests**

Test exact source IDs, operator/name aliases, coordinate distance, capacity/date similarity, multi-source merging, false-positive separation, precision retention, and all-source preservation.

**Step 2: Verify failure**

Run: `cd pipeline && python -m pytest tests/test_canonicalize.py -q`  
Expected: FAIL.

**Step 3: Implement canonicalization**

Use deterministic rules first and conservative similarity matching second. Assign exact points spatially; assign city/region centroids only to the labelled parent geography. Never manufacture a point from a country-only announcement.

**Step 4: Verify tests**

Run: `cd pipeline && python -m pytest tests/test_canonicalize.py -q`  
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/canonicalize.py pipeline/src/grid_scope/storage.py pipeline/tests/test_canonicalize.py
git commit -m "feat: canonicalize global infrastructure assets"
```

### Task 7: Publish validated global snapshots with last-known-good fallback

**Files:**
- Modify: `pipeline/src/grid_scope/snapshot_builder.py`
- Modify: `pipeline/src/grid_scope/publisher.py`
- Modify: `pipeline/src/grid_scope/cli.py`
- Modify: `pipeline/tests/test_snapshot_builder.py`
- Modify: `pipeline/tests/test_publisher.py`
- Modify: `pipeline/tests/test_cli.py`
- Modify: `scripts/refresh-snapshot.sh`

**Step 1: Write failing publication tests**

Require artifacts for countries, regions, assets, evidence, and manifest; coverage summaries by country/category; score modes; UN disclaimer; connector timestamps; atomic promotion; stale fallback; and rejection of suspicious row-count or score changes.

**Step 2: Verify failure**

Run: `cd pipeline && python -m pytest tests/test_snapshot_builder.py tests/test_publisher.py tests/test_cli.py -q`  
Expected: FAIL against the Europe-only artifact set.

**Step 3: Implement global publication**

Publish compact versioned artifacts:

```text
countries.geojson
regions.geojson
assets.geojson
evidence.json
manifest.json
```

Promote `latest.json` only after schema, geometry, unit, date, duplicate, row-delta, and score-delta validation. Preserve the previous pointer on any critical failure.

**Step 4: Verify publication tests**

Run: `cd pipeline && python -m pytest tests/test_snapshot_builder.py tests/test_publisher.py tests/test_cli.py -q`  
Expected: PASS.

**Step 5: Generate a local snapshot and inspect it**

Run: `./scripts/refresh-snapshot.sh`  
Expected: a new versioned snapshot with non-empty countries and assets plus an updated `web/public/data/latest.json`.

**Step 6: Commit**

```bash
git add pipeline scripts web/public/data
git commit -m "feat: publish validated global snapshots"
```

### Task 8: Load the global snapshot in the web application

**Files:**
- Modify: `web/lib/snapshot/types.ts`
- Modify: `web/lib/snapshot/schema.ts`
- Modify: `web/lib/snapshot/load.ts`
- Modify: `web/tests/snapshot.test.ts`
- Modify: `web/app/page.tsx`

**Step 1: Write failing loader tests**

Test all five artifacts, global metadata, category scores, demand ranges, level labels, source linkage, and a stale-but-valid latest snapshot.

**Step 2: Verify failure**

Run: `cd web && npm test -- snapshot.test.ts`  
Expected: FAIL because the loader expects regions/projects only.

**Step 3: Implement loader migration**

Parse and validate the complete snapshot once on the server. Pass typed immutable data to the client workspace. Fail with an actionable message only when neither latest nor a last-known-good snapshot is valid.

**Step 4: Verify tests**

Run: `cd web && npm test -- snapshot.test.ts`  
Expected: PASS.

**Step 5: Commit**

```bash
git add web/lib/snapshot web/tests/snapshot.test.ts web/app/page.tsx
git commit -m "feat: load Wattlas global snapshots"
```

### Task 9: Replace the Europe map with the global geographic hierarchy

**Files:**
- Rename: `web/components/map/europe-map.tsx` to `web/components/map/global-map.tsx`
- Modify: `web/components/map/map-style.ts`
- Modify: `web/lib/map/expressions.ts`
- Modify: `web/tests/expressions.test.ts`
- Create: `web/tests/global-map.test.tsx`

**Step 1: Write failing map-expression and component tests**

Test fixed country score colors, missing/inherited patterns, thick country lines, zoom-dependent regional visibility, stronger selection, category-specific symbols, and accessible global labels.

**Step 2: Verify failure**

Run: `cd web && npm test -- expressions.test.ts global-map.test.tsx`  
Expected: FAIL.

**Step 3: Implement global MapLibre layers**

Use separate sources and ordered layers for country fills, inherited hatch treatment, country borders, subnational fills, subnational borders, selected geometry, clustered assets, data-centre symbols, and water symbols. Start at a world extent and fit bounds responsively. Keep country borders visible and thicker than regional lines at every zoom.

**Step 4: Verify tests**

Run: `cd web && npm test -- expressions.test.ts global-map.test.tsx`  
Expected: PASS.

**Step 5: Commit**

```bash
git add web/components/map web/lib/map web/tests
git commit -m "feat: add Wattlas global map"
```

### Task 10: Add category toggles, global search, ranking, and selection

**Files:**
- Modify: `web/components/opportunity-radar.tsx`
- Modify: `web/components/controls/command-bar.tsx`
- Modify: `web/components/controls/layer-rail.tsx`
- Create: `web/components/controls/infrastructure-toggle.tsx`
- Create: `web/components/ranking/opportunity-ranking.tsx`
- Create: `web/lib/search.ts`
- Modify: `web/tests/opportunity-radar.test.tsx`
- Create: `web/tests/search.test.ts`

**Step 1: Write failing interaction tests**

Test Combined/Data Centres/Water Infrastructure modes, recalculated rankings, country-to-region drill-down, project selection, search across names/operators, unavailable states, and persistence of the selected lens and year.

**Step 2: Verify failure**

Run: `cd web && npm test -- opportunity-radar.test.tsx search.test.ts`  
Expected: FAIL.

**Step 3: Implement workspace state and controls**

Keep infrastructure category, analytical lens, year, geography level, and selection as separate state. Combined is the default. Search results must show entity type and location. Rankings must compare only the same peer level and visibly exclude non-rankable records.

**Step 4: Verify tests**

Run: `cd web && npm test -- opportunity-radar.test.tsx search.test.ts`  
Expected: PASS.

**Step 5: Commit**

```bash
git add web/components web/lib/search.ts web/tests
git commit -m "feat: add global search and infrastructure controls"
```

### Task 11: Build the global inspector and evidence experience

**Files:**
- Rename: `web/components/inspector/region-inspector.tsx` to `web/components/inspector/entity-inspector.tsx`
- Modify: `web/components/inspector/evidence-dossier.tsx`
- Modify: `web/components/comparison/comparison-drawer.tsx`
- Modify: `web/components/status/data-status-drawer.tsx`
- Create: `web/tests/entity-inspector.test.tsx`

**Step 1: Write failing inspector tests**

Require score arithmetic, low/base/high MW, category mix, lifecycle timeline, source links, confidence explanation, value-kind labels, location precision, peer-level label, inherited warning, stale connector state, and plain-language explanations.

**Step 2: Verify failure**

Run: `cd web && npm test -- entity-inspector.test.tsx`  
Expected: FAIL.

**Step 3: Implement the inspector**

Support country, subnational geography, data centre, and water asset selections. Keep Infrastructure Demand, Site Attractiveness, and System Risk visibly distinct. Do not present a blended master score. Hide download actions in this release.

**Step 4: Verify tests**

Run: `cd web && npm test -- entity-inspector.test.tsx`  
Expected: PASS.

**Step 5: Commit**

```bash
git add web/components web/tests/entity-inspector.test.tsx
git commit -m "feat: explain global Wattlas evidence"
```

### Task 12: Polish the responsive Wattlas interface

**Files:**
- Modify: `web/app/globals.css`
- Modify: `web/app/page.module.css`
- Modify: `web/components/controls/timeline.tsx`
- Modify: `web/components/opportunity-radar.tsx`
- Modify: `web/tests/e2e/radar.spec.ts`

**Step 1: Extend end-to-end assertions**

Test desktop, tablet, and mobile viewports; keyboard focus; search; toggles; map load; selection; inspector scrolling; evidence opening; and status messaging.

**Step 2: Verify expected failures**

Run: `cd web && npm run e2e`  
Expected: new global/responsive assertions fail before the polish pass.

**Step 3: Implement the approved visual hierarchy**

Retain the dark control-room character, improve public readability, use strong national boundaries, restrained analytical color, periwinkle data-centre markers, mint water markers, and amber combined demand. Keep dense analysis desktop-first while making core inspection usable on mobile.

**Step 4: Verify end-to-end tests**

Run: `cd web && npm run e2e`  
Expected: PASS.

**Step 5: Commit**

```bash
git add web/app web/components web/tests/e2e/radar.spec.ts
git commit -m "style: polish responsive Wattlas workspace"
```

### Task 13: Add daily refresh automation and deployment readiness

**Files:**
- Create: `.github/workflows/refresh-wattlas.yml`
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `web/README.md`
- Modify: `product-facts.md`
- Modify: `PROJECT_CONTEXT.md`

**Step 1: Add workflow validation expectations**

The workflow must install Python and Node dependencies, run pipeline tests, refresh into a temporary snapshot, run snapshot validation, run web tests/build, and commit generated data only when the snapshot changes and all checks pass. Include manual dispatch and a daily schedule.

**Step 2: Implement automation and documentation**

Document local refresh, environment variables, source licences, last-known-good behavior, GitHub repository setup, Vercel import, daily-refresh semantics, and the fact that production deployment is deferred until the Wattlas repository exists.

**Step 3: Validate configuration**

Run: `make test && make build`  
Expected: Python tests, Vitest, lint, and Next.js production build all pass.

**Step 4: Commit**

```bash
git add .github Makefile README.md web/README.md product-facts.md PROJECT_CONTEXT.md
git commit -m "chore: prepare Wattlas daily refresh and deployment"
```

### Task 14: Full verification and browser acceptance

**Files:**
- Modify only if verification reveals defects.

**Step 1: Run the complete automated suite**

Run:

```bash
cd pipeline && python -m pytest
cd ../web && npm test
npm run lint
npm run build
npm run e2e
```

Expected: all commands PASS.

**Step 2: Run a clean daily refresh**

Run: `cd .. && ./scripts/refresh-snapshot.sh`  
Expected: a validated global snapshot is published and the previous snapshot remains intact.

**Step 3: Perform browser QA at `http://127.0.0.1:3000/`**

Verify:

- World view and thick UN national boundaries.
- Country and available subnational drill-down.
- Combined, Data Centres, and Water Infrastructure toggles.
- Search, ranking, year changes, and all three analytical lenses.
- Data-centre and water symbols across multiple world regions.
- Score arithmetic, MW ranges, confidence, source links, and location precision.
- Inherited, unavailable, stale, and connector-failure states.
- Desktop, tablet, and mobile layouts.

**Step 4: Audit evidence and licences**

Confirm every demand-contributing asset has a public source, no commercial directory content is redistributed, the UN disclaimer is visible, and the UI uses “daily refreshed.”

**Step 5: Commit any verification fixes**

```bash
git add <only-files-changed-by-verification>
git commit -m "fix: complete Wattlas global verification"
```

**Step 6: Record handoff**

Update `PROJECT_CONTEXT.md` with test results, snapshot ID, global country count, native subnational count, asset counts by category, known source gaps, and the exact GitHub/Vercel connection steps remaining.
