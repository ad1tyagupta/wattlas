# Wattlas Global Regions and Facility Details Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add selectable global first-level administrative regions, an India boundary override using the Government of India perspective, and substantially richer facility records and inspection without changing Wattlas's approved scoring model.

**Architecture:** Build and version-pin a browser-safe global ADM1 artifact separately from the daily facility refresh, retain Europe NUTS-2 as a deeper layer, and override India's national/ADM1 geometry with the approved India perspective. Extend the OSM/QLever contract, then spatially assign every facility to the most specific available geography and publish regional context/scoring summaries. The web app loads the new immutable artifact, applies the approved zoom hierarchy, and presents grouped facility evidence.

**Tech Stack:** Python 3.13, Pydantic, httpx, Shapely, pytest, Next.js 16, React 19, TypeScript, MapLibre GL, Zod, Vitest, Playwright, GitHub, Vercel.

---

### Task 1: Add pinned global ADM1 and India boundary connectors

**Files:**
- Create: `pipeline/src/grid_scope/connectors/geoboundaries.py`
- Create: `pipeline/tests/fixtures/geoboundaries-adm1-sample.json`
- Create: `pipeline/tests/fixtures/india-adm1-sample.json`
- Modify: `pipeline/src/grid_scope/config.py`
- Modify: `pipeline/tests/test_connectors.py`

**Steps:**
1. Write failing tests for metadata parsing, Polygon/MultiPolygon normalization, stable IDs, parent ISO codes, source metadata, and India perspective metadata.
2. Run `cd pipeline && python -m pytest tests/test_connectors.py -q` and confirm the expected failure.
3. Implement pinned-source connectors with injected HTTP/file inputs, deterministic IDs, source attribution, and coverage guardrails.
4. Re-run the connector tests and commit.

### Task 2: Normalize, simplify, validate, and publish regional geometry

**Files:**
- Create: `pipeline/src/grid_scope/boundaries.py`
- Modify: `pipeline/src/grid_scope/models.py`
- Modify: `pipeline/src/grid_scope/snapshot_builder.py`
- Modify: `pipeline/src/grid_scope/publisher.py`
- Modify: `pipeline/tests/test_models.py`
- Modify: `pipeline/tests/test_snapshot_builder.py`
- Modify: `pipeline/tests/test_publisher.py`

**Steps:**
1. Write failing tests requiring unique global ADM1 IDs, valid geometry, parent countries, simplified browser-safe output, India country override, and explicit Jammu and Kashmir, Ladakh, Assam, and Arunachal Pradesh coverage.
2. Run the focused tests and verify RED.
3. Implement boundary normalization/simplification, validation, last-known-good behavior, and immutable `admin1.geojson` publication while retaining `regions.geojson` for Europe NUTS-2.
4. Verify GREEN and commit.

### Task 3: Assign facilities and calculate regional intelligence

**Files:**
- Create: `pipeline/src/grid_scope/geography.py`
- Modify: `pipeline/src/grid_scope/snapshot_builder.py`
- Modify: `pipeline/tests/test_snapshot_builder.py`

**Steps:**
1. Write failing tests for point-to-ADM1/NUTS-2 assignment, country/region facility counts, source/category/lifecycle splits, and score isolation for operational assets.
2. Run the tests and verify the missing behavior.
3. Implement most-specific geography assignment and regional summaries using the existing explainable score engine; operational infrastructure stays context-only.
4. Run the focused and full pipeline tests, then commit.

### Task 4: Enrich the public facility data contract

**Files:**
- Modify: `pipeline/src/grid_scope/connectors/osm_infrastructure.py`
- Modify: `pipeline/src/grid_scope/models.py`
- Modify: `pipeline/src/grid_scope/canonicalize.py`
- Modify: `pipeline/tests/fixtures/qlever-osm-infrastructure-sample.json`
- Modify: `pipeline/tests/test_connectors.py`
- Modify: `pipeline/tests/test_models.py`
- Modify: `pipeline/tests/test_canonicalize.py`

**Steps:**
1. Write failing tests for owner, website, references, address parts, dates, explicit power, Wikidata/Wikipedia identifiers, coordinate precision, provenance, and honest unavailable values.
2. Verify RED.
3. Extend the QLever query/parser and asset contract, preserving only reported power values and official-over-community merge precedence.
4. Verify focused and full pipeline tests, then commit.

### Task 5: Load the new artifacts and enriched records in the web app

**Files:**
- Modify: `web/lib/snapshot/schema.ts`
- Modify: `web/lib/snapshot/types.ts`
- Modify: `web/lib/snapshot/load.ts`
- Modify: `web/tests/snapshot.test.ts`

**Steps:**
1. Write failing schema/loader tests for `admin1.geojson`, regional summaries, India perspective metadata, and enriched optional facility fields.
2. Verify RED with `cd web && npm test -- snapshot.test.ts`.
3. Extend runtime validation and immutable snapshot loading while preserving compatibility with valid earlier snapshots.
4. Verify GREEN and commit.

### Task 6: Render and select the global boundary hierarchy

**Files:**
- Modify: `web/components/map/global-map.tsx`
- Modify: `web/lib/map/expressions.ts`
- Modify: `web/tests/global-map.test.tsx`
- Modify: `web/tests/expressions.test.ts`

**Steps:**
1. Write failing tests for strong national borders, global ADM1 medium-zoom lines/fills, deeper Europe NUTS-2 styling, India perspective attribution, and ADM1 selection.
2. Verify RED.
3. Add the MapLibre source/layers, zoom hierarchy, hover/selection state, and approved attribution without disturbing marker clustering.
4. Verify focused map tests and commit.

### Task 7: Add regional and grouped facility inspection

**Files:**
- Modify: `web/components/opportunity-radar.tsx`
- Modify: `web/components/inspector/entity-inspector.tsx`
- Modify: `web/components/inspector/evidence-dossier.tsx`
- Modify: `web/app/globals.css`
- Modify: `web/tests/opportunity-radar.test.tsx`
- Modify: `web/tests/entity-inspector.test.tsx`

**Steps:**
1. Write failing interaction tests for regional summaries and grouped Identity, Location, Operations, Energy, and Sources facility details with direct public links and unavailable states.
2. Verify RED.
3. Implement typed ADM1 selection and the expanded evidence-first inspector, preserving all three analytical lenses and the 2026–2031 state.
4. Verify focused UI tests and commit.

### Task 8: Generate, validate, and document the production snapshot

**Files:**
- Modify: `pipeline/src/grid_scope/cli.py`
- Modify: `pipeline/tests/test_cli.py`
- Modify: `web/public/snapshots/**`
- Modify: `README.md`
- Modify: `PROJECT_CONTEXT.md`

**Steps:**
1. Write failing refresh tests for cached boundaries, artifact manifests, coverage drops, and India validation.
2. Verify RED, implement refresh integration, then verify GREEN.
3. Generate a production snapshot with global ADM1 coverage and enriched facilities; run the snapshot validator and inspect counts/size.
4. Update documentation and validated project decisions, then commit.

### Task 9: Full verification, publication, and production smoke test

**Steps:**
1. Run the complete Python test suite, Vitest suite, lint, Next.js production build, and Playwright tests.
2. Start the built application and verify world/ADM1/NUTS-2 layers, India perspective attribution and required regions, rich facility inspection, responsive layout, and zero browser errors.
3. Review the final diff and ensure no secrets, temporary files, or unrelated changes are included.
4. Push the implementation branch, update `main` as authorized, monitor Vercel, and verify the production URL and dataset counts.

