# Wattlas Global Facility Coverage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Wattlas's 14-record sample asset layer with validated global OpenStreetMap infrastructure coverage merged with the curated official project registry.

**Architecture:** A daily QLever connector fetches supported OpenStreetMap facility tags, converts OSM geometry to representative coordinates, assigns UN countries, and normalizes records into the existing asset contract. Canonicalization merges only strong duplicates and gives curated official records precedence. Operational assets remain context-only, while forward-looking demand-backed projects continue to drive the explainable 2026–2031 scores. The web app clusters the expanded GeoJSON and supports facility inspection.

**Tech Stack:** Python 3.13, Pydantic, httpx, DuckDB, pytest, Next.js 16, React 19, TypeScript, MapLibre GL, Zod, Vitest, Playwright, GitHub, Vercel.

---

### Task 1: Add the QLever OpenStreetMap infrastructure connector

**Files:**
- Create: `pipeline/src/grid_scope/connectors/osm_infrastructure.py`
- Modify: `pipeline/src/grid_scope/config.py`
- Modify: `pipeline/tests/test_connectors.py`
- Create: `pipeline/tests/fixtures/qlever-osm-infrastructure-sample.json`

**Step 1: Write failing connector tests**

Test that the parser:

- converts SPARQL JSON bindings into data-centre and desalination records;
- accepts point and polygon WKT;
- generates deterministic labels for unnamed records;
- maps lifecycle query values to Wattlas lifecycle values;
- preserves OSM element URLs, operators, provenance, and observation time;
- rejects malformed geometry and unexpectedly small production responses.

**Step 2: Verify failure**

Run: `cd pipeline && python -m pytest tests/test_connectors.py -q`

Expected: FAIL because `OsmInfrastructureConnector` does not exist.

**Step 3: Implement the connector**

Add a QLever SPARQL query covering:

- `telecom=data_center` as operational data centres;
- supported construction/proposed data-centre tags;
- `water_works=desalination` and `man_made=desalination_plant` as water infrastructure.

Request element URI, name, operator, geometry, start/opening dates, and lifecycle classification. Parse WKT into representative coordinates, produce stable IDs from OSM element type/ID, and label all records `community_mapped`. Add `QLEVER_OSM_URL` to configuration.

**Step 4: Verify tests**

Run: `cd pipeline && python -m pytest tests/test_connectors.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/connectors/osm_infrastructure.py pipeline/src/grid_scope/config.py pipeline/tests/test_connectors.py pipeline/tests/fixtures/qlever-osm-infrastructure-sample.json
git commit -m "feat: ingest global OSM infrastructure"
```

### Task 2: Normalize, geolocate, and merge community facilities

**Files:**
- Modify: `pipeline/src/grid_scope/models.py`
- Modify: `pipeline/src/grid_scope/canonicalize.py`
- Modify: `pipeline/src/grid_scope/connectors/global_assets.py`
- Modify: `pipeline/tests/test_models.py`
- Modify: `pipeline/tests/test_canonicalize.py`

**Step 1: Write failing data-contract tests**

Require `sourceType`, `sourceUrl`, `externalIds`, `lastObservedAt`, and optional `operator`. Test point-in-country assignment against Polygon and MultiPolygon boundaries. Test that strong duplicates merge, curated official values win, source IDs combine, and uncertain colocated buildings remain separate.

**Step 2: Verify failure**

Run: `cd pipeline && python -m pytest tests/test_models.py tests/test_canonicalize.py -q`

Expected: FAIL on missing provenance fields and merge precedence.

**Step 3: Implement normalization and precedence**

Extend the asset contract and canonicalization helpers. Add deterministic country assignment using UN geometry. Merge community and curated records only through shared external IDs or strong operator/name/proximity agreement. Mark curated assets `official_verified` during registry loading and retain their lifecycle, MW, precision, and evidence when merging.

**Step 4: Verify tests**

Run: `cd pipeline && python -m pytest tests/test_models.py tests/test_canonicalize.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/models.py pipeline/src/grid_scope/canonicalize.py pipeline/src/grid_scope/connectors/global_assets.py pipeline/tests/test_models.py pipeline/tests/test_canonicalize.py
git commit -m "feat: merge official and community facilities"
```

### Task 3: Publish expanded assets without polluting forward-demand scores

**Files:**
- Modify: `pipeline/src/grid_scope/snapshot_builder.py`
- Modify: `pipeline/src/grid_scope/publisher.py`
- Modify: `pipeline/tests/test_snapshot_builder.py`
- Modify: `pipeline/tests/test_publisher.py`

**Step 1: Write failing scoring and publication tests**

Test that:

- operational assets without MW remain visible but do not contribute to scores;
- only eligible forward-looking demand-backed assets create future MW;
- countries expose total, operational, planned, category, official, and community counts;
- asset GeoJSON retains provenance and source URLs;
- publication rejects fewer than 3,500 data centres in a production OSM snapshot, duplicate IDs, invalid coordinates, or unknown country assignments.

**Step 2: Verify failure**

Run: `cd pipeline && python -m pytest tests/test_snapshot_builder.py tests/test_publisher.py -q`

Expected: FAIL on context/scoring separation and missing summaries.

**Step 3: Implement expanded publication**

Separate `context_assets` from `scoring_assets`, add country summaries, and retain all valid point features in `assets.geojson`. Add coverage guardrails to the publisher/refresh boundary without applying the 3,500 threshold to small unit-test fixtures.

**Step 4: Verify tests**

Run: `cd pipeline && python -m pytest tests/test_snapshot_builder.py tests/test_publisher.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/snapshot_builder.py pipeline/src/grid_scope/publisher.py pipeline/tests/test_snapshot_builder.py pipeline/tests/test_publisher.py
git commit -m "feat: publish global facility context"
```

### Task 4: Integrate QLever into the daily refresh with fallback

**Files:**
- Modify: `pipeline/src/grid_scope/cli.py`
- Modify: `pipeline/src/grid_scope/storage.py`
- Modify: `pipeline/tests/test_cli.py`
- Modify: `.github/workflows/refresh-wattlas.yml`

**Step 1: Write failing refresh tests**

Test successful OSM capture/merge, last-known-good fallback, connector status, coverage counts, and failure when neither a current nor cached response meets the minimum threshold.

**Step 2: Verify failure**

Run: `cd pipeline && python -m pytest tests/test_cli.py -q`

Expected: FAIL because refresh does not call QLever.

**Step 3: Implement refresh integration**

Fetch QLever through the existing raw-capture boundary, normalize and country-assign community records, merge them with curated records, validate coverage, then publish. Preserve previous validated raw data on connector failure and expose current/cached/failed state in the manifest. Ensure the daily workflow has enough timeout for the public query and still validates the generated snapshot before committing it.

**Step 4: Verify tests**

Run: `cd pipeline && python -m pytest tests/test_cli.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline/src/grid_scope/cli.py pipeline/src/grid_scope/storage.py pipeline/tests/test_cli.py .github/workflows/refresh-wattlas.yml
git commit -m "feat: refresh community facilities daily"
```

### Task 5: Load provenance and facility summaries in the web app

**Files:**
- Modify: `web/lib/snapshot/schema.ts`
- Modify: `web/lib/snapshot/types.ts`
- Modify: `web/tests/snapshot.test.ts`

**Step 1: Write failing schema tests**

Require source type, source URL, operator, lifecycle, observation time, location precision, external IDs, and country summary counts. Load a fixture containing both community and official assets.

**Step 2: Verify failure**

Run: `cd web && npm test -- snapshot.test.ts`

Expected: FAIL on missing schema fields.

**Step 3: Extend the runtime schema**

Add the approved optional and required fields while preserving compatibility with immutable earlier snapshots. Export asset feature types suitable for selection and inspection.

**Step 4: Verify tests**

Run: `cd web && npm test -- snapshot.test.ts`

Expected: PASS.

**Step 5: Commit**

```bash
git add web/lib/snapshot/schema.ts web/lib/snapshot/types.ts web/tests/snapshot.test.ts
git commit -m "feat: load facility provenance"
```

### Task 6: Cluster and select global facilities

**Files:**
- Modify: `web/components/map/global-map.tsx`
- Modify: `web/lib/map/expressions.ts`
- Modify: `web/tests/global-map.test.tsx`
- Modify: `web/tests/expressions.test.ts`

**Step 1: Write failing map tests**

Require a clustered asset source, count-label layer, progressive cluster expansion, category-colored individual markers, lifecycle/source-type styling, and asset-selection events.

**Step 2: Verify failure**

Run: `cd web && npm test -- global-map.test.tsx expressions.test.ts`

Expected: FAIL because the current source is unclustered and asset clicks select only geography IDs.

**Step 3: Implement clustering and selection**

Enable MapLibre GeoJSON clustering, add cluster circles/counts, expand clusters on click, and keep periwinkle/mint facility markers below cluster level. Return typed selection objects distinguishing country, region, and asset.

**Step 4: Verify tests**

Run: `cd web && npm test -- global-map.test.tsx expressions.test.ts`

Expected: PASS.

**Step 5: Commit**

```bash
git add web/components/map/global-map.tsx web/lib/map/expressions.ts web/tests/global-map.test.tsx web/tests/expressions.test.ts
git commit -m "feat: cluster global infrastructure facilities"
```

### Task 7: Add facility and country coverage inspection

**Files:**
- Modify: `web/components/opportunity-radar.tsx`
- Rename: `web/components/inspector/region-inspector.tsx` to `web/components/inspector/entity-inspector.tsx`
- Modify: `web/components/inspector/evidence-dossier.tsx`
- Modify: `web/app/globals.css`
- Modify: `web/tests/opportunity-radar.test.tsx`
- Create: `web/tests/entity-inspector.test.tsx`

**Step 1: Write failing interaction tests**

Test asset selection and display of operator, lifecycle, provenance, location precision, exact OSM/official source URL, observation date, and MW availability. Test country totals split by operational/planned, category, and official/community source. Preserve the three analytical lenses and year state.

**Step 2: Verify failure**

Run: `cd web && npm test -- opportunity-radar.test.tsx entity-inspector.test.tsx`

Expected: FAIL because assets are not selectable entities.

**Step 3: Implement entity inspection**

Use a discriminated selection state for geography and asset entities. Render facility-specific inspection without inventing scores. For country selection, add facility coverage summaries alongside the existing explainable score. Keep external source links explicit and accessible.

**Step 4: Verify tests**

Run: `cd web && npm test -- opportunity-radar.test.tsx entity-inspector.test.tsx`

Expected: PASS.

**Step 5: Commit**

```bash
git add web/components web/app/globals.css web/tests/opportunity-radar.test.tsx web/tests/entity-inspector.test.tsx
git commit -m "feat: inspect global facilities"
```

### Task 8: Refresh the global snapshot and update documentation

**Files:**
- Create: `web/public/data/snapshots/<generated-id>/countries.geojson`
- Create: `web/public/data/snapshots/<generated-id>/regions.geojson`
- Create: `web/public/data/snapshots/<generated-id>/assets.geojson`
- Create: `web/public/data/snapshots/<generated-id>/evidence.json`
- Modify: `web/public/data/latest.json`
- Modify: `README.md`
- Modify: `web/README.md`
- Modify: `product-facts.md`
- Modify: `PROJECT_CONTEXT.md`

**Step 1: Run the real refresh**

Run: `./scripts/refresh-snapshot.sh`

Expected: a new validated immutable snapshot containing at least 3,500 data centres and the supported desalination records.

**Step 2: Audit the snapshot**

Verify unique IDs, valid coordinates, recognized countries, provenance counts, category counts, lifecycle counts, official/community counts, and that operational assets do not create future MW.

**Step 3: Update documentation**

Document OSM/QLever provenance, ODbL attribution, coverage caveats, daily refresh behavior, minimum-count fallback, current snapshot ID, and exact counts.

**Step 4: Commit**

```bash
git add web/public/data README.md web/README.md product-facts.md PROJECT_CONTEXT.md
git commit -m "data: publish expanded global facilities"
```

### Task 9: Full verification, production deployment, and Git push

**Files:**
- Modify only if verification reveals defects.

**Step 1: Run the full automated suite**

```bash
cd pipeline && python -m pytest
cd ../web && npm test
npm run lint
npm run build
npm run e2e
```

Expected: all commands PASS.

**Step 2: Run browser acceptance locally**

Verify world clustering, cluster expansion, thousands of facilities, country summaries, asset inspection, official/community provenance, source links, category styling, analytical lenses, and responsive layouts with no browser errors.

**Step 3: Push both branches**

```bash
git push origin feature/opportunity-radar
git push origin HEAD:main
```

**Step 4: Wait for Vercel production**

Inspect the Git-triggered production deployment until it is READY and aliased to `https://wattlas.vercel.app`.

**Step 5: Verify production**

Use a clean browser session to confirm the live manifest count, clustered map canvas, asset selection, provenance display, and zero console/page errors. Confirm GitHub main, the feature branch, local HEAD, and the Vercel deployment refer to the same commit.
