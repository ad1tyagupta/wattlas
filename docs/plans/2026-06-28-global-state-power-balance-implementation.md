# Wattlas Global State Power Balance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make global ADM1 regions visibly selectable and data-rich, add utility-scale power-generation facilities, calculate transparent current and 2026–2031 regional electricity balances, and ship a fourth Power Balance lens with persistent Aditya Gupta attribution.

**Architecture:** Extend the Python snapshot pipeline with three versioned inputs: global population, electricity-demand controls/official regional observations, and canonical power plants. Precompute compact ADM1 summaries and global generator overview points, publish individual generators in country shards, and keep all heavy data client-loaded. Preserve Infrastructure Demand as the primary score while adding an explainable Power Balance pressure score and raw balance metrics.

**Tech Stack:** Python 3.13, Pydantic, httpx, DuckDB, Shapely, Rasterio, pytest, Next.js 16, React 19, TypeScript, MapLibre GL, Zod, Vitest, Playwright, GitHub, Vercel.

**Approved design:** `docs/plans/2026-06-28-global-state-power-balance-design.md`

---

## Source and delivery rules

- Use public, redistributable data only.
- Treat official ADM1 observations as higher precedence than modelled values.
- Use WorldPop Global2 for population gap-filling.
- Use reusable official plant registries first, Global Energy Monitor GIPT second, WRI Global Power Plant Database third, and OpenStreetMap as community fallback.
- Do not automate around a download form or access restriction. Accept a configured local GEM release path when a stable public file URL is not available.
- Keep country control totals, official regional observations, model weights, assumptions, and model outputs as separate artifacts.
- Do not call demand minus local generation a definitive deficit when interchange is unknown.
- Use a global ADM1 generator overview at world zoom and lazily loaded country plant shards at closer zoom; do not load the complete plant catalogue into the initial page.

---

### Task 1: Extend the Python contracts for regional electricity and power generation

**Files:**
- Modify: `pipeline/src/grid_scope/models.py`
- Modify: `pipeline/tests/test_models.py`

**Step 1: Write failing contract tests**

Add tests for:

```python
from grid_scope.models import (
    AssetCategory,
    GenerationTechnology,
    PowerBalanceMetrics,
    RegionalEnergyForecast,
)


def test_power_generation_contract_keeps_reported_and_estimated_supply_separate():
    assert AssetCategory.POWER_GENERATION == "power_generation"
    metrics = PowerBalanceMetrics(
        demand_gwh={"low": 980, "central": 1000, "high": 1040},
        local_generation_gwh={"low": 760, "central": 820, "high": 890},
        local_generation_gap_gwh={"low": 90, "central": 180, "high": 280},
        net_balance_gwh=None,
        observed_unmet_demand_gwh=None,
        installed_capacity_mw=420,
        dependable_capacity_mw={"low": 210, "central": 275, "high": 330},
        peak_demand_mw={"low": 290, "central": 310, "high": 340},
    )
    assert metrics.local_generation_gap_gwh.central == 180
    assert metrics.net_balance_gwh is None


def test_power_generation_asset_requires_technology_and_capacity_lineage():
    # Construct a power-generation AssetProperties record and assert that
    # technology, capacity, source IDs, lifecycle, and value kind survive JSON output.
    ...
```

Require:

- `AssetCategory.POWER_GENERATION`;
- `GenerationTechnology`: solar, wind, hydro, nuclear, gas, coal, oil, biomass, geothermal, other;
- optional secondary fuel;
- `capacityMw`, `dependableCapacityMw`, `annualGenerationGwh` ranges;
- `commissioningYear`, `retirementYear`, `plantId`, `unitId`;
- `PowerBalanceMetrics` with distinct local gap, net balance, and observed unmet demand;
- `RegionalEnergyForecast` for each year 2026–2031;
- method ID, source IDs, confidence, coverage, and value kind.

**Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest pipeline/tests/test_models.py -q
```

Expected: FAIL because the generation and balance contracts do not exist.

**Step 3: Implement the minimal contracts**

Add bounded Pydantic models. Reuse the existing ordered range type where units are clear; otherwise create `MetricRange`. Add validators that:

- require evidence for reported or estimated capacity;
- reject negative demand, generation, capacity, and unmet demand;
- require `low <= central <= high`;
- keep net balance signed;
- reject `power_generation` assets without a technology;
- prevent target years outside 2026–2031 for forward projects.

**Step 4: Run focused and full model tests**

```bash
.venv/bin/python -m pytest pipeline/tests/test_models.py -q
.venv/bin/python -m pytest pipeline/tests -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/models.py pipeline/tests/test_models.py
git commit -m "feat: model regional electricity balance"
```

---

### Task 2: Add reusable power-plant source parsers

**Files:**
- Create: `pipeline/src/grid_scope/connectors/gem_power.py`
- Create: `pipeline/src/grid_scope/connectors/wri_power.py`
- Create: `pipeline/src/grid_scope/connectors/osm_power.py`
- Create: `pipeline/tests/fixtures/gem-power-sample.csv`
- Create: `pipeline/tests/fixtures/wri-power-sample.json`
- Create: `pipeline/tests/fixtures/qlever-osm-power-sample.json`
- Modify: `pipeline/src/grid_scope/config.py`
- Modify: `pipeline/tests/test_connectors.py`

**Step 1: Write failing source-normalization tests**

Cover:

- GEM plant/unit hierarchy and lifecycle values;
- WRI primary/secondary fuel and generation history;
- OSM `power=plant` records, excluding household/rooftop generators;
- technology aliases such as `photovoltaic -> solar`, `onshore_wind -> wind`, `CCGT -> gas`;
- reported capacity versus unavailable capacity;
- operating, construction, pre-construction/planned, retired, cancelled, and shelved states;
- source URL, licence, update date, external IDs, coordinates, owner, and operator;
- malformed coordinates and impossible capacity;
- minimum production coverage guards.

Example:

```python
def test_gem_parser_preserves_plant_and_unit_identity():
    records = parse_gem_power(FIXTURES / "gem-power-sample.csv")
    nuclear = next(item for item in records if item["externalIds"]["gemUnit"] == "GEM-U-1")
    assert nuclear["category"] == "power_generation"
    assert nuclear["technology"] == "nuclear"
    assert nuclear["capacityMw"]["central"] == 1_200
    assert nuclear["plantId"] == "gem-plant-GEM-P-1"
```

**Step 2: Verify RED**

```bash
.venv/bin/python -m pytest pipeline/tests/test_connectors.py -q
```

Expected: import failures for the new connectors.

**Step 3: Implement parsers and connector boundaries**

- `GemPowerConnector` reads a configured CC BY 4.0 CSV/Excel release from `GEM_GIPT_PATH` or a stable configured public URL; it is `not_configured` when neither exists.
- `WriPowerConnector` fetches the configured WRI data/API resource with checksum capture.
- `OsmPowerConnector` queries QLever for utility-scale `power=plant` features and preserves ODbL attribution.
- Keep source-specific records intact until canonicalization.
- Add configuration keys without embedding credentials or private URLs.

**Step 4: Verify GREEN**

```bash
.venv/bin/python -m pytest pipeline/tests/test_connectors.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/connectors pipeline/src/grid_scope/config.py pipeline/tests
git commit -m "feat: ingest public power plants"
```

---

### Task 3: Canonicalize plants, units, technologies, and ADM1 assignment

**Files:**
- Create: `pipeline/src/grid_scope/power_plants.py`
- Modify: `pipeline/src/grid_scope/canonicalize.py`
- Modify: `pipeline/tests/test_canonicalize.py`
- Create: `pipeline/tests/test_power_plants.py`

**Step 1: Write failing canonicalization tests**

Test that:

- a shared GEM/WRI/OSM external ID merges records;
- conservative name/operator/location/capacity matching merges only strong duplicates;
- units remain addressable while rolling up into a plant summary;
- official/GEM values outrank community values field by field;
- source IDs and aliases combine;
- multi-fuel plants retain secondary fuel;
- exact points receive the most specific ADM1/NUTS-2 assignment;
- uncertain colocated facilities remain separate;
- retired/cancelled capacity does not count as operating supply.

**Step 2: Verify RED**

```bash
.venv/bin/python -m pytest pipeline/tests/test_canonicalize.py pipeline/tests/test_power_plants.py -q
```

Expected: FAIL on missing power-plant canonicalization.

**Step 3: Implement canonicalization**

Use this precedence:

```python
SOURCE_RANK = {
    "official_verified": 4,
    "research_verified": 3,  # GEM/WRI
    "community_mapped": 2,
    "modelled": 1,
}
```

Do not overwrite a reported value with an estimate. Produce a plant summary containing unit counts and operating/planned capacity by technology, while keeping unit records in the canonical warehouse.

**Step 4: Verify GREEN and regression suite**

```bash
.venv/bin/python -m pytest pipeline/tests/test_canonicalize.py pipeline/tests/test_power_plants.py -q
.venv/bin/python -m pytest pipeline/tests -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/power_plants.py pipeline/src/grid_scope/canonicalize.py pipeline/tests
git commit -m "feat: canonicalize global power plants"
```

---

### Task 4: Build versioned ADM1 population estimates with official overrides

**Files:**
- Create: `pipeline/src/grid_scope/population.py`
- Create: `pipeline/src/grid_scope/connectors/worldpop.py`
- Create: `scripts/build-admin1-population.py`
- Create: `data/curated/admin1-population-overrides.csv`
- Create: `pipeline/tests/fixtures/worldpop-tiny.tif`
- Create: `pipeline/tests/fixtures/admin1-small.geojson`
- Create: `pipeline/tests/test_population.py`
- Modify: `pipeline/pyproject.toml`
- Modify: `.gitignore`

**Step 1: Write failing zonal and precedence tests**

Use a tiny generated GeoTIFF fixture and two simple polygons. Test:

- nodata pixels do not become population;
- raster cells aggregate to the correct ADM1;
- totals are non-negative integers;
- official overrides replace modelled estimates only for matching geography/year;
- modelled values retain WorldPop release, source year, confidence, and value kind;
- 2026–2031 values exist where Global2 supports them;
- countries/territories without population remain unavailable.

**Step 2: Verify RED**

```bash
.venv/bin/python -m pytest pipeline/tests/test_population.py -q
```

Expected: FAIL because the population builder does not exist.

**Step 3: Implement the offline population build**

- Add `rasterio` to pipeline dependencies.
- Stream raster windows; do not load the 5.2 GB global source into memory.
- Aggregate to the exact active Wattlas ADM1 geometry.
- Reconcile country sums to WorldPop/UN-aligned country totals within a documented tolerance.
- Write compact `data/curated/admin1-population.json` containing 2026–2031 values, not the raster.
- Keep downloaded rasters under ignored `data/cache/worldpop/`.
- The daily refresh reads the compact versioned artifact; population is rebuilt only when its upstream release changes.

**Step 4: Verify tests and a fixture build**

```bash
.venv/bin/python -m pytest pipeline/tests/test_population.py -q
.venv/bin/python scripts/build-admin1-population.py \
  --boundaries pipeline/tests/fixtures/admin1-small.geojson \
  --worldpop pipeline/tests/fixtures/worldpop-tiny.tif \
  --output /tmp/admin1-population.json
```

Expected: PASS and a deterministic compact artifact.

**Step 5: Commit**

```bash
git add pipeline/pyproject.toml pipeline/src/grid_scope/population.py pipeline/src/grid_scope/connectors/worldpop.py scripts/build-admin1-population.py data/curated/admin1-population-overrides.csv pipeline/tests .gitignore
git commit -m "feat: aggregate ADM1 population"
```

---

### Task 5: Add country electricity controls and official regional observations

**Files:**
- Expand: `pipeline/src/grid_scope/connectors/ember.py`
- Create: `pipeline/src/grid_scope/connectors/eia.py`
- Create: `pipeline/src/grid_scope/connectors/regional_electricity.py`
- Create: `data/curated/regional-electricity-observed.csv`
- Create: `pipeline/tests/fixtures/ember-yearly-sample.csv`
- Create: `pipeline/tests/fixtures/eia-state-sample.json`
- Create: `pipeline/tests/test_regional_electricity.py`
- Modify: `pipeline/src/grid_scope/config.py`

**Step 1: Write failing observation tests**

Require normalized records for:

- country annual demand/consumption and generation controls;
- ADM1 annual demand/sales, generation, peak demand, interchange, and unmet demand;
- fuel/technology generation mix;
- unit and period metadata;
- official values taking precedence over curated/modelled values;
- unavailable interchange remaining `None`;
- source freshness and licence.

Example:

```python
def test_eia_state_balance_keeps_interchange_separate():
    record = normalize_eia_state(FIXTURE)[0]
    assert record["geographyId"] == "US-..."
    assert record["demandGwh"] == 82_400
    assert record["localGenerationGwh"] == 75_000
    assert record["netInterchangeGwh"] == 7_700
    assert record["observedUnmetDemandGwh"] is None
```

**Step 2: Verify RED**

```bash
.venv/bin/python -m pytest pipeline/tests/test_regional_electricity.py pipeline/tests/test_connectors.py -q
```

Expected: FAIL on missing connector behavior.

**Step 3: Implement source adapters**

- Expand Ember normalization to select country, year, metric, unit, and fuel.
- Add EIA API v2 normalization for state sales/generation/capability and balancing-authority interchange where mappable.
- Load additional official ADM1 observations from a normalized curated file with per-row source IDs; do not scrape unstable PDFs in the daily pipeline.
- Add explicit mappings from source region codes to Wattlas geography IDs.
- Reject country totals and ADM1 observations with incompatible units.

**Step 4: Verify GREEN**

```bash
.venv/bin/python -m pytest pipeline/tests/test_regional_electricity.py pipeline/tests/test_connectors.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/connectors pipeline/src/grid_scope/config.py data/curated/regional-electricity-observed.csv pipeline/tests
git commit -m "feat: ingest regional electricity observations"
```

---

### Task 6: Build transparent ADM1 demand-allocation weights

**Files:**
- Create: `pipeline/src/grid_scope/regional_demand.py`
- Create: `scripts/build-regional-demand-weights.py`
- Create: `data/curated/regional-demand-methods.json`
- Create: `pipeline/tests/test_regional_demand.py`

**Step 1: Write failing model tests**

Test three method grades:

1. `official`: direct regional observation.
2. `multi_covariate`: population plus gridded electricity/nighttime-light/economic and industrial weights.
3. `population_only`: population share with wider uncertainty.

Assertions:

```python
def test_modelled_regions_reconcile_exactly_to_country_control():
    result = allocate_country_demand(
        country_gwh=1_000,
        regions=[
            {"id": "AA-1", "populationShare": 0.4, "activityShare": 0.5},
            {"id": "AA-2", "populationShare": 0.6, "activityShare": 0.5},
        ],
    )
    assert round(sum(item["demandGwh"]["central"] for item in result), 6) == 1_000
    assert all(item["valueKind"] == "estimated" for item in result)
```

Also test official residual allocation: official regions are fixed first; only the remaining country total is allocated across modelled regions.

**Step 2: Verify RED**

```bash
.venv/bin/python -m pytest pipeline/tests/test_regional_demand.py -q
```

Expected: FAIL.

**Step 3: Implement the model**

- Store normalized covariate shares, not raw rasters, in `data/curated/regional-demand-weights.json`.
- Default multi-covariate central weight:

```text
0.55 electricity-activity/nighttime-light share
+ 0.30 population share
+ 0.15 industrial-facility proxy share
```

- Renormalize available components and disclose the effective weights.
- Use uncertainty bands based on method grade and source age.
- Do not add operating data-centre/water loads twice to the historical country control. Add only documented forward increments to forecasts.
- Reconcile all modelled ADM1 central values to their country control within `1e-6` relative tolerance.

**Step 4: Verify GREEN**

```bash
.venv/bin/python -m pytest pipeline/tests/test_regional_demand.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/regional_demand.py scripts/build-regional-demand-weights.py data/curated/regional-demand-methods.json pipeline/tests/test_regional_demand.py
git commit -m "feat: model ADM1 electricity demand"
```

---

### Task 7: Calculate dependable capacity, generation, balance, and forecasts

**Files:**
- Create: `pipeline/src/grid_scope/power_balance.py`
- Create: `data/curated/generation-assumptions.json`
- Create: `pipeline/tests/test_power_balance.py`
- Modify: `pipeline/src/grid_scope/demand.py`

**Step 1: Write failing arithmetic tests**

Test:

- reported annual generation wins over capacity-factor estimation;
- capacity-factor estimates use `capacity_mw * 8.76 * capacity_factor` GWh;
- dependable capacity uses capacity credit, not capacity factor;
- operating plants count in current supply;
- planned/construction plants count only from their expected year and with lifecycle delivery factors;
- retired capacity disappears after retirement year;
- local gap equals demand minus local generation;
- known interchange creates net balance;
- unknown interchange leaves net balance unavailable;
- observed unmet demand is never inferred from local gap;
- forward data-centre and water demand ranges are added once;
- each 2026–2031 year preserves ordered low/base/high ranges.

**Step 2: Verify RED**

```bash
.venv/bin/python -m pytest pipeline/tests/test_power_balance.py -q
```

Expected: FAIL.

**Step 3: Implement supply and forecast methods**

Put technology assumptions in the versioned JSON file. Each assumption contains:

- low/base/high capacity factor;
- low/base/high dependable-capacity credit;
- planned/announced/construction delivery factor;
- source and method note.

Prefer country/technology observed capacity factors derived from official/Ember generation and capacity when adequate. Fall back to global technology ranges with lower confidence.

**Step 4: Verify GREEN**

```bash
.venv/bin/python -m pytest pipeline/tests/test_power_balance.py -q
.venv/bin/python -m pytest pipeline/tests -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/power_balance.py pipeline/src/grid_scope/demand.py data/curated/generation-assumptions.json pipeline/tests/test_power_balance.py
git commit -m "feat: calculate regional power balances"
```

---

### Task 8: Add the explainable Power Balance pressure score

**Files:**
- Modify: `pipeline/src/grid_scope/scoring.py`
- Modify: `pipeline/src/grid_scope/models.py`
- Modify: `pipeline/tests/test_scoring.py`

**Step 1: Write failing score tests**

Require the approved weights:

- 35 capacity margin;
- 30 annual local balance;
- 15 observed unmet demand;
- 10 forecast demand growth;
- 10 supply delivery gap.

Test missing-data re-normalization:

```python
def test_power_balance_score_exposes_effective_denominator():
    result = score_power_balance(
        capacity_margin_index=80,
        local_balance_index=60,
        observed_unmet_demand_index=None,
        demand_growth_index=70,
        supply_delivery_index=50,
        source_ids=["source-a"],
    )
    assert result.available_points == 85
    assert result.score == pytest.approx((80*35 + 60*30 + 70*10 + 50*10) / 85)
    assert len(result.contributions) == 5
```

Also assert that an unavailable component contributes neither zero points nor denominator weight.

**Step 2: Verify RED**

```bash
.venv/bin/python -m pytest pipeline/tests/test_scoring.py -q
```

Expected: FAIL because Power Balance is absent.

**Step 3: Implement score and contribution metadata**

- Add `powerBalance` to lens scores.
- Return contribution raw values, units, normalization, points, maximum points, value kind, source IDs, and method version.
- Withhold a rankable score below the approved minimum coverage threshold.
- Keep Infrastructure Demand ordering and semantics unchanged.

**Step 4: Verify GREEN**

```bash
.venv/bin/python -m pytest pipeline/tests/test_scoring.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/scoring.py pipeline/src/grid_scope/models.py pipeline/tests/test_scoring.py
git commit -m "feat: score regional power balance"
```

---

### Task 9: Publish compact regional energy and scalable generator artifacts

**Files:**
- Modify: `pipeline/src/grid_scope/snapshot_builder.py`
- Modify: `pipeline/src/grid_scope/publisher.py`
- Create: `pipeline/src/grid_scope/generator_artifacts.py`
- Modify: `pipeline/tests/test_snapshot_builder.py`
- Modify: `pipeline/tests/test_publisher.py`

**Step 1: Write failing artifact tests**

Require:

- compact ADM1 properties include population and Power Balance score/year summary;
- full regional time series live in `regional-energy.json`, keyed by geography ID;
- `generator-overview.geojson` contains one aggregate point per populated ADM1 with count, capacity, mix, and dominant technology;
- `generators/index.json` contains country bbox, shard path, feature count, checksum, and bytes;
- `generators/{ISO}.geojson` contains individual canonical plants for that country;
- the complete plant catalogue is not copied into the ADM1 artifact or initial HTML;
- generator and regional totals reconcile to canonical warehouse totals;
- unknown country/ADM1 assignments and duplicate IDs block publication;
- India validations remain intact;
- artifact-size and feature-count guards retain the last good snapshot.

**Step 2: Verify RED**

```bash
.venv/bin/python -m pytest pipeline/tests/test_snapshot_builder.py pipeline/tests/test_publisher.py -q
```

Expected: FAIL on missing new artifacts.

**Step 3: Implement artifact generation**

Publish:

```text
countries.geojson
admin1.geojson
regions.geojson
assets.geojson
regional-energy.json
generator-overview.geojson
generators/index.json
generators/US.geojson
generators/IN.geojson
...
evidence.json
```

Use country-scoped spatial indexes. Include checksums for nested shard files in the manifest. Keep full regional methods and source lists out of map geometry.

**Step 4: Verify GREEN**

```bash
.venv/bin/python -m pytest pipeline/tests/test_snapshot_builder.py pipeline/tests/test_publisher.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/snapshot_builder.py pipeline/src/grid_scope/publisher.py pipeline/src/grid_scope/generator_artifacts.py pipeline/tests
git commit -m "feat: publish regional energy and generator shards"
```

---

### Task 10: Integrate sources, fallbacks, and model builds into the refresh

**Files:**
- Modify: `pipeline/src/grid_scope/cli.py`
- Modify: `pipeline/src/grid_scope/storage.py`
- Modify: `pipeline/tests/test_cli.py`
- Modify: `scripts/refresh-snapshot.sh`
- Modify: `.env.example`

**Step 1: Write failing refresh tests**

Test:

- current official/GEM/WRI/OSM source precedence;
- optional GEM local release state;
- last-known-good source fallback;
- country controls plus official regional observations plus modelled residuals;
- versioned population and model-weight artifact use;
- generator coverage and canonicalization counts;
- source-specific observation dates;
- publication failure on reconciliation or coverage drops;
- retention of the previous `latest.json` on any final validation failure.

**Step 2: Verify RED**

```bash
.venv/bin/python -m pytest pipeline/tests/test_cli.py -q
```

Expected: FAIL.

**Step 3: Implement orchestration**

Order the refresh:

```text
boundaries -> population -> plant sources -> plant canonicalization
-> country electricity controls -> official ADM1 observations
-> modelled ADM1 residual demand -> supply/balance/forecast
-> scores -> artifacts -> validation -> atomic publish
```

Do not rebuild WorldPop/raster weights daily. Check their version metadata and use the committed compact artifact. Ensure daily status means “checked today,” not “observed today.”

**Step 4: Verify GREEN**

```bash
.venv/bin/python -m pytest pipeline/tests/test_cli.py -q
.venv/bin/python -m pytest pipeline/tests -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/cli.py pipeline/src/grid_scope/storage.py pipeline/tests/test_cli.py scripts/refresh-snapshot.sh .env.example
git commit -m "feat: refresh global power balance data"
```

---

### Task 11: Extend the web snapshot contract and lazy loaders

**Files:**
- Modify: `web/lib/snapshot/schema.ts`
- Modify: `web/lib/snapshot/types.ts`
- Modify: `web/lib/snapshot/load.ts`
- Create: `web/lib/snapshot/generators.ts`
- Modify: `web/tests/snapshot.test.ts`

**Step 1: Write failing runtime-schema tests**

Cover:

- `power_generation` category and generation technologies;
- fourth `powerBalance` lens;
- compact ADM1 population/balance fields;
- full regional-energy forecast records;
- generator overview and country shard schemas;
- signed net balance;
- distinct local gap and observed unmet demand;
- generator index checksum/path/size;
- rejected invalid technology, capacity, dates, and ranges;
- server loader excludes heavy generator shards from RSC/HTML;
- client loader caches country shard promises and validates responses.

**Step 2: Verify RED**

```bash
cd web && npm test -- snapshot.test.ts
```

Expected: FAIL.

**Step 3: Implement schemas and loaders**

- Load countries, compact regions, asset context, and evidence server-side as today.
- Load ADM1, regional-energy details, generator overview, and visible-country shards client-side.
- Abort stale fetches on unmount and cache successful immutable paths.
- Surface a recoverable layer error rather than crashing the map.

**Step 4: Verify GREEN**

```bash
cd web && npm test -- snapshot.test.ts
```

Expected: PASS.

**Step 5: Commit**

```bash
git add web/lib/snapshot web/tests/snapshot.test.ts
git commit -m "feat: load power balance snapshot data"
```

---

### Task 12: Make global ADM1 borders and labels unmistakable

**Files:**
- Modify: `web/components/map/global-map.tsx`
- Modify: `web/lib/map/expressions.ts`
- Modify: `web/tests/global-map.test.tsx`
- Modify: `web/tests/expressions.test.ts`

**Step 1: Write failing layer tests**

Require:

- ADM1 lines are present from the initial world zoom;
- zoom-interpolated line width and opacity;
- national borders stay stronger;
- collision-aware ADM1 label layer starts at medium zoom;
- NUTS-2 begins later than ADM1;
- unavailable regions remain selectable;
- selected/hovered ADM1 gets a visible outline;
- Power Balance uses a diverging expression with unavailable styling;
- country-level-only exceptions remain selectable without fabricated internal lines.

**Step 2: Verify RED**

```bash
cd web && npm test -- global-map.test.tsx expressions.test.ts
```

Expected: FAIL on current ADM1 `minzoom` and missing labels.

**Step 3: Implement the boundary hierarchy**

Use zoom expressions instead of a hard visibility cliff:

```ts
"line-width": ["interpolate", ["linear"], ["zoom"], 1, 0.35, 3, 0.8, 6, 1.25]
"line-opacity": ["interpolate", ["linear"], ["zoom"], 1, 0.28, 3, 0.65, 6, 0.9]
```

Use a dedicated centroid/label point artifact if polygon labels are unstable. Preserve thick country lines above regional layers.

**Step 4: Verify GREEN**

```bash
cd web && npm test -- global-map.test.tsx expressions.test.ts
```

Expected: PASS.

**Step 5: Commit**

```bash
git add web/components/map/global-map.tsx web/lib/map/expressions.ts web/tests
git commit -m "feat: reveal global state boundaries"
```

---

### Task 13: Add generator overview, country-shard loading, colours, and filters

**Files:**
- Create: `web/lib/map/generator-colors.ts`
- Create: `web/lib/map/generator-shards.ts`
- Modify: `web/components/map/global-map.tsx`
- Modify: `web/components/controls/layer-rail.tsx`
- Modify: `web/components/opportunity-radar.tsx`
- Create: `web/tests/generator-colors.test.ts`
- Modify: `web/tests/global-map.test.tsx`
- Modify: `web/tests/opportunity-radar.test.tsx`

**Step 1: Write failing interaction and colour tests**

Assert exact semantic mapping:

```ts
expect(generatorColor("solar")).toBe("#E7B84B");
expect(generatorColor("wind")).toBe("#55C7D9");
expect(generatorColor("hydro")).toBe("#4E8EDB");
expect(generatorColor("nuclear")).toBe("#A98AE8");
```

Also cover gas, coal, oil, biomass, geothermal, and other. Test:

- independent data-centre, water, and generator toggles;
- technology and lifecycle filters;
- world overview markers before shards load;
- visible-country bbox selection;
- one immutable fetch per country shard;
- cached shards combine into the active source;
- moving away removes rendered features without dropping cache;
- marker shape/outline differentiates infrastructure families;
- mixed clusters are neutral and expose composition;
- generator selection returns a typed generator entity.

**Step 2: Verify RED**

```bash
cd web && npm test -- generator-colors.test.ts global-map.test.tsx opportunity-radar.test.tsx
```

Expected: FAIL.

**Step 3: Implement layer delivery and controls**

- Render `generator-overview` below medium zoom.
- On `moveend` at medium zoom, intersect map bounds with the generator index and request only visible country shards.
- Limit concurrent shard fetches and abort stale requests.
- Use MapLibre clustering on the active visible-country source.
- Keep the three infrastructure-family toggles independent.
- Add accessible technology swatches and pressed states.

**Step 4: Verify GREEN**

```bash
cd web && npm test -- generator-colors.test.ts global-map.test.tsx opportunity-radar.test.tsx
```

Expected: PASS.

**Step 5: Commit**

```bash
git add web/lib/map web/components web/tests
git commit -m "feat: map power generators by technology"
```

---

### Task 14: Add Power Balance lens and regional/generator inspection

**Files:**
- Modify: `web/components/controls/layer-rail.tsx`
- Modify: `web/components/inspector/entity-inspector.tsx`
- Modify: `web/components/inspector/evidence-dossier.tsx`
- Create: `web/components/inspector/power-balance-chart.tsx`
- Modify: `web/components/comparison/comparison-drawer.tsx`
- Modify: `web/components/opportunity-radar.tsx`
- Modify: `web/app/globals.css`
- Modify: `web/tests/entity-inspector.test.tsx`
- Modify: `web/tests/opportunity-radar.test.tsx`
- Create: `web/tests/power-balance-chart.test.tsx`

**Step 1: Write failing UI tests**

Require the regional inspector to show:

- population, source year, forecast growth, and value kind;
- current demand GWh and peak MW;
- local generation GWh and dependable capacity MW;
- local generation gap;
- net balance only when interchange exists;
- observed unmet demand only when reported;
- generation mix and plant counts by lifecycle;
- data-centre and water forward demand;
- a 2026–2031 low/base/high demand-versus-supply chart;
- Power Balance contribution arithmetic and coverage;
- direct sources and method note.

Require generator inspection to show technology, fuel, capacity, generation, status, dates, owner/operator, location, confidence, and source.

**Step 2: Verify RED**

```bash
cd web && npm test -- entity-inspector.test.tsx opportunity-radar.test.tsx power-balance-chart.test.tsx
```

Expected: FAIL.

**Step 3: Implement the fourth lens and inspectors**

- Add `Power Balance` without changing the default Infrastructure Demand lens.
- Label estimates and unavailable values in plain language.
- Never shorten `local generation gap` to `deficit`.
- Draw accessible SVG ranges with a text/table fallback.
- Keep charts responsive and avoid adding a charting dependency unless the SVG implementation proves insufficient.

**Step 4: Verify GREEN**

```bash
cd web && npm test -- entity-inspector.test.tsx opportunity-radar.test.tsx power-balance-chart.test.tsx
```

Expected: PASS.

**Step 5: Commit**

```bash
git add web/components web/app/globals.css web/tests
git commit -m "feat: inspect regional power balance"
```

---

### Task 15: Add creator credit and complete source-status disclosure

**Files:**
- Modify: `web/components/map/global-map.tsx`
- Modify: `web/components/status/data-status-drawer.tsx`
- Modify: `web/app/globals.css`
- Modify: `web/tests/global-map.test.tsx`
- Modify: `web/tests/opportunity-radar.test.tsx`

**Step 1: Write failing attribution tests**

Require:

```ts
expect(screen.getByText("Created by Aditya Gupta")).toBeVisible();
expect(screen.getByRole("link", { name: "Open-source project" }))
  .toHaveAttribute("href", "https://github.com/ad1tyagupta/wattlas");
```

Also verify keyboard focus, accessible contrast class, dataset attributions, India perspective attribution, and source-specific observation dates.

**Step 2: Verify RED**

```bash
cd web && npm test -- global-map.test.tsx opportunity-radar.test.tsx
```

Expected: FAIL because the credit does not exist.

**Step 3: Implement subtle persistent credit**

Place `Created by Aditya Gupta · Open-source project` in the map attribution area using existing muted mono typography. Keep it visible at desktop and mobile without covering MapLibre controls.

**Step 4: Verify GREEN**

```bash
cd web && npm test -- global-map.test.tsx opportunity-radar.test.tsx
```

Expected: PASS.

**Step 5: Commit**

```bash
git add web/components/map/global-map.tsx web/components/status/data-status-drawer.tsx web/app/globals.css web/tests
git commit -m "feat: add Wattlas creator attribution"
```

---

### Task 16: Generate and validate the production dataset

**Files:**
- Create or modify: `data/curated/admin1-population.json`
- Create or modify: `data/curated/regional-demand-weights.json`
- Modify: `web/public/data/latest.json`
- Create: `web/public/data/snapshots/<snapshot-id>/regional-energy.json`
- Create: `web/public/data/snapshots/<snapshot-id>/generator-overview.geojson`
- Create: `web/public/data/snapshots/<snapshot-id>/generators/index.json`
- Create: `web/public/data/snapshots/<snapshot-id>/generators/*.geojson`
- Modify: `README.md`
- Modify: `PROJECT_CONTEXT.md`

**Step 1: Run source builds with production inputs**

```bash
.venv/bin/python scripts/build-admin1-population.py \
  --boundaries data/curated/global-admin1.geojson \
  --worldpop data/cache/worldpop/population_G2_R2025A_v1.tif \
  --overrides data/curated/admin1-population-overrides.csv \
  --output data/curated/admin1-population.json

.venv/bin/python scripts/build-regional-demand-weights.py \
  --boundaries data/curated/global-admin1.geojson \
  --population data/curated/admin1-population.json \
  --output data/curated/regional-demand-weights.json

.venv/bin/python -m grid_scope.cli refresh
```

**Step 2: Validate coverage and quality**

Require reports for:

- countries and ADM1 regions with borders;
- countries legitimately remaining country-level;
- regions with official versus modelled population;
- regions with official versus modelled demand;
- canonical plants and units by technology/status/source;
- regions with reported generation versus capacity-factor estimates;
- regions with net balance and observed unmet demand;
- Power Balance rankable coverage;
- artifact bytes and client-load budgets;
- India required regions;
- checksums and duplicate IDs.

Stop if coverage drops unexpectedly or reconciliation fails.

**Step 3: Update documentation**

Document exact snapshot counts, model version, source releases, limitations, refresh cadence, and terminology. Preserve Europe-first, public-data-only, 2026–2031, Opportunity Radar, Infrastructure Demand primary, and supporting lenses.

**Step 4: Run snapshot-loading tests**

```bash
cd web && npm test -- snapshot.test.ts
```

Expected: PASS against the generated production snapshot.

**Step 5: Commit**

```bash
git add data/curated web/public/data README.md PROJECT_CONTEXT.md
git commit -m "data: publish global state power balance"
```

---

### Task 17: Full verification, browser QA, push, and Vercel validation

**Files:**
- Modify if needed: `web/tests/e2e/radar.spec.ts`

**Step 1: Add end-to-end coverage for the complete user story**

Test:

```text
load world map
-> verify ADM1 lines visible at initial zoom
-> select a state outside Europe
-> inspect population and power balance
-> switch to Power Balance
-> enable generator layer
-> filter solar and construction
-> select a plant
-> inspect capacity and source
-> verify creator credit
```

Cover desktop 1440×900, in-app pane 760×820, and mobile 390×844 with no horizontal overflow.

**Step 2: Run the fresh full verification gate**

```bash
.venv/bin/python -m pytest pipeline/tests -q
cd web && npm test
cd web && npm run lint
cd web && npm run build
cd web && npm run e2e
```

Expected: all commands exit 0.

**Step 3: Run rendered browser QA**

Verify:

- meaningful first screen and no framework overlay;
- ADM1 visibility at world/medium/close zoom;
- state selection outside Europe;
- generator overview and country shard loading;
- technology colours and colour-blind differentiation;
- Power Balance raw values and terminology;
- creator credit;
- desktop/mobile screenshots;
- zero relevant browser console errors.

**Step 4: Review and publish**

```bash
git diff --check
git status --short
git log --oneline --decorate -15
git push -u origin <feature-branch>
git push origin HEAD:main
```

Do not include caches, downloaded rasters, credentials, temporary screenshots, or unrelated user changes.

**Step 5: Verify production**

Confirm:

- Vercel deployment status is Ready;
- `https://wattlas.vercel.app/data/latest.json` has the new model version and artifacts;
- ADM1, regional energy, generator overview, and country shards are reachable;
- production counts match the manifest;
- India required regions remain present;
- creator credit and GitHub link render;
- no production error logs appear after smoke requests.

Commit any test-only corrections before re-running the entire gate and pushing again.

---

## Final requirement checklist

- [ ] Global ADM1 boundaries are visible from world view and strengthen with zoom.
- [ ] Every legitimate published ADM1 is selectable and labelled at the appropriate zoom.
- [ ] Country-level-only exceptions are explicit; no subdivisions are fabricated.
- [ ] Population is official where available and WorldPop-modelled elsewhere.
- [ ] Utility-scale power plants include operating, construction, and planned records.
- [ ] Solar, wind, hydro, nuclear, gas, coal, oil, biomass, geothermal, and other have distinct accessible styles.
- [ ] Data-centre, water, and generator layers toggle independently.
- [ ] Local generation gap, net balance, and observed unmet demand are separate.
- [ ] Demand and supply expose low/base/high 2026–2031 paths.
- [ ] Dependable capacity is not confused with nameplate capacity.
- [ ] Power Balance is a fourth explainable lens; Infrastructure Demand remains primary.
- [ ] Every modelled value exposes method, source, date, confidence, and value kind.
- [ ] Heavy generator records are sharded and lazy-loaded.
- [ ] `Created by Aditya Gupta · Open-source project` is persistently visible and linked.
- [ ] Full Python, Vitest, lint, build, Playwright, browser, GitHub, Vercel, and production-data verification pass.
