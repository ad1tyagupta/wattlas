# Opportunity Radar Working Version Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private, daily-refreshed Europe Opportunity Radar with an interactive MapLibre map, explainable 2026–2031 scores, source freshness, evidence dossiers, and last-known-good snapshot behavior.

**Architecture:** A Python/DuckDB batch pipeline produces immutable, validated GeoJSON/JSON snapshots. A Next.js App Router application reads only the latest published snapshot through a typed adapter and renders a MapLibre analytical canvas. The UI never calls upstream public sources directly, so source failures cannot break the map.

**Tech Stack:** Next.js 16.2.9, React 19.2.7, TypeScript, MapLibre GL JS 5.24.0, Vitest 4.1.9, Playwright 1.61.1, Python 3.13, DuckDB 1.5.x, Pydantic 2, HTTPX, pytest.

---

## Scope decomposition

This plan delivers one vertical slice. It includes the snapshot contract, daily pipeline, initial public connectors, scoring, map, filters, inspector, comparison, evidence, and freshness. The 3D globe, scenario controls, authentication, alerts, and public deployment remain separate future plans.

## File map

```text
.
├── .gitignore                         # generated files, secrets, caches
├── .env.example                       # optional connector credentials
├── Makefile                           # local setup, test, refresh, run commands
├── data/
│   ├── curated/launch-clusters.json   # analyst-reviewed claims and metrics
│   ├── fixtures/                      # deterministic connector fixtures
│   ├── raw/.gitkeep                   # immutable fetched payloads, gitignored
│   └── warehouse/.gitkeep             # DuckDB database, gitignored
├── pipeline/
│   ├── pyproject.toml
│   ├── src/grid_scope/
│   │   ├── cli.py                     # refresh command and exit codes
│   │   ├── config.py                  # paths, environment, model version
│   │   ├── models.py                  # claims, observations, scores, manifest
│   │   ├── storage.py                 # raw capture and DuckDB persistence
│   │   ├── quality.py                 # validation and publication gates
│   │   ├── scoring.py                 # lens formulas and confidence
│   │   ├── publisher.py               # atomic immutable snapshot publishing
│   │   └── connectors/
│   │       ├── base.py                # connector protocol and status result
│   │       ├── gisco.py               # NUTS 2 geometry
│   │       ├── eurostat.py            # population/context API
│   │       ├── entsoe.py              # optional token-backed electricity data
│   │       └── curated.py             # claim-level launch-cluster registry
│   └── tests/
│       ├── test_models.py
│       ├── test_scoring.py
│       ├── test_quality.py
│       ├── test_connectors.py
│       └── test_publisher.py
├── scripts/refresh-snapshot.sh         # one-command daily refresh
└── web/
    ├── package.json
    ├── next.config.ts
    ├── tsconfig.json
    ├── vitest.config.ts
    ├── playwright.config.ts
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx
    │   └── globals.css
    ├── components/
    │   ├── opportunity-radar.tsx       # application state composition
    │   ├── map/europe-map.tsx          # MapLibre lifecycle and layers
    │   ├── map/map-style.ts            # blank cartographic base style
    │   ├── controls/command-bar.tsx
    │   ├── controls/layer-rail.tsx
    │   ├── controls/timeline.tsx
    │   ├── inspector/region-inspector.tsx
    │   ├── inspector/evidence-dossier.tsx
    │   ├── comparison/comparison-drawer.tsx
    │   └── status/data-status-drawer.tsx
    ├── lib/
    │   ├── snapshot/schema.ts          # TypeScript snapshot contract
    │   ├── snapshot/load.ts            # validated artifact loading
    │   ├── map/expressions.ts          # lens-specific color expressions
    │   └── format.ts                   # dates, units, confidence labels
    ├── public/data/                    # pipeline-owned published snapshots
    └── tests/
        ├── snapshot.test.ts
        ├── opportunity-radar.test.tsx
        └── radar.spec.ts
```

### Task 1: Establish the workspace and reproducible toolchains

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `Makefile`
- Create: `pipeline/pyproject.toml`
- Create: `web/package.json`

- [ ] **Step 1: Create ignore and environment contracts**

```gitignore
.DS_Store
.env
.next/
node_modules/
__pycache__/
.pytest_cache/
.venv/
data/raw/**
!data/raw/.gitkeep
data/warehouse/**
!data/warehouse/.gitkeep
web/public/data/snapshots/**
!web/public/data/snapshots/.gitkeep
test-results/
playwright-report/
.superpowers/
```

```dotenv
ENTSOE_SECURITY_TOKEN=
CDS_API_KEY=
GRID_SCOPE_TIMEZONE=Europe/Berlin
GRID_SCOPE_PUBLISH_DIR=web/public/data
```

- [ ] **Step 2: Define Python dependencies and commands**

```toml
[project]
name = "grid-scope-pipeline"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
  "duckdb>=1.5,<1.6",
  "httpx>=0.28,<0.29",
  "pydantic>=2.11,<3",
  "python-dateutil>=2.9,<3",
]

[project.optional-dependencies]
dev = ["pytest>=8.4,<9", "pytest-cov>=6.2,<7", "respx>=0.22,<0.23"]

[project.scripts]
grid-scope-refresh = "grid_scope.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-q --strict-markers"
```

- [ ] **Step 3: Define the web package**

Use `npm create next-app@16.2.9 web -- --ts --eslint --app --src-dir=false --use-npm --no-tailwind --import-alias='@/*'`, then add:

```bash
cd web
npm install maplibre-gl@5.24.0 zod@4.1.12
npm install -D vitest@4.1.9 @vitejs/plugin-react@latest jsdom@latest @testing-library/react@latest @testing-library/jest-dom@latest @playwright/test@1.61.1
```

- [ ] **Step 4: Add root commands**

```makefile
.PHONY: setup test refresh dev verify
setup:
	python3 -m venv .venv
	.venv/bin/pip install -e 'pipeline[dev]'
	cd web && npm install

test:
	.venv/bin/pytest pipeline/tests
	cd web && npm test

refresh:
	./scripts/refresh-snapshot.sh

dev:
	cd web && npm run dev

verify: test
	cd web && npm run build
	cd web && npx playwright test
```

- [ ] **Step 5: Verify clean setup**

Run: `make setup && make test`  
Expected: dependencies install; test commands report no tests collected or pass once Task 2 lands.

### Task 2: Define one snapshot contract in Python and TypeScript

**Files:**
- Create: `pipeline/src/grid_scope/models.py`
- Create: `pipeline/tests/test_models.py`
- Create: `web/lib/snapshot/schema.ts`
- Create: `web/tests/snapshot.test.ts`

- [ ] **Step 1: Write failing Python model tests**

```python
from datetime import UTC, datetime
import pytest
from pydantic import ValidationError
from grid_scope.models import ConnectorState, LensScores, RegionProperties, ValueKind

def test_region_rejects_score_outside_range() -> None:
    with pytest.raises(ValidationError):
        RegionProperties(
            id="DE71", name="Darmstadt", country="DE", score_year=2030,
            scores=LensScores(infrastructure_demand=101, site_attractiveness=60, system_risk=40),
            confidence=72, coverage=76, value_kind=ValueKind.ESTIMATED,
            updated_at=datetime.now(UTC),
        )

def test_connector_state_names_are_stable() -> None:
    assert {state.value for state in ConnectorState} == {
        "current", "cached", "stale", "failed", "not_configured"
    }
```

- [ ] **Step 2: Implement the Python contract**

Define enums `ConnectorState`, `ValueKind`, and `LifecycleState`; models `SourceRef`, `EvidenceClaim`, `ScoreContribution`, `LensScores`, `RegionProperties`, `ProjectProperties`, `ConnectorStatus`, and `SnapshotManifest`. Constrain scores/confidence/coverage to `0..100`, years to `2026..2031`, require timezone-aware timestamps, and require source IDs on every non-unavailable contribution.

- [ ] **Step 3: Run Python contract tests**

Run: `.venv/bin/pytest pipeline/tests/test_models.py -v`  
Expected: PASS.

- [ ] **Step 4: Mirror the contract with Zod**

```ts
import { z } from "zod";

export const connectorStateSchema = z.enum([
  "current", "cached", "stale", "failed", "not_configured",
]);
export const valueKindSchema = z.enum([
  "observed", "reported", "estimated", "inherited", "unavailable",
]);
export const scoreSchema = z.number().min(0).max(100).nullable();
export const lensScoresSchema = z.object({
  infrastructureDemand: scoreSchema,
  siteAttractiveness: scoreSchema,
  systemRisk: scoreSchema,
});
export const manifestSchema = z.object({
  snapshotId: z.string().min(1),
  generatedAt: z.string().datetime(),
  modelVersion: z.string().min(1),
  activeYears: z.array(z.number().int().min(2026).max(2031)).length(6),
  artifacts: z.object({ regions: z.string(), projects: z.string(), evidence: z.string() }),
  connectors: z.array(z.object({
    id: z.string(), state: connectorStateSchema, checkedAt: z.string().datetime(),
    lastSuccessAt: z.string().datetime().nullable(), message: z.string().nullable(),
  })),
});
export type SnapshotManifest = z.infer<typeof manifestSchema>;
```

- [ ] **Step 5: Test invalid and valid manifests in Vitest**

Run: `cd web && npm test -- snapshot.test.ts`  
Expected: malformed timestamps and score ranges fail; a fixture manifest passes.

### Task 3: Implement raw capture, connector status, and last-known-good storage

**Files:**
- Create: `pipeline/src/grid_scope/config.py`
- Create: `pipeline/src/grid_scope/connectors/base.py`
- Create: `pipeline/src/grid_scope/storage.py`
- Create: `pipeline/tests/test_connectors.py`

- [ ] **Step 1: Write failure-first storage tests**

Test that identical bytes reuse the same SHA-256 capture, failed connector runs do not remove the last successful capture, and missing credentials return `not_configured` rather than `failed`.

- [ ] **Step 2: Implement connector result types**

```python
@dataclass(frozen=True)
class FetchPayload:
    source_id: str
    retrieved_at: datetime
    media_type: str
    body: bytes

@dataclass(frozen=True)
class ConnectorResult:
    source_id: str
    state: ConnectorState
    payload: FetchPayload | None
    message: str | None = None
```

The `Connector` protocol exposes `source_id` and `fetch(client, now) -> ConnectorResult`.

- [ ] **Step 3: Persist immutable captures**

Write captures to `data/raw/<source>/<YYYY-MM-DD>/<sha256>.<ext>` and upsert metadata into `data/warehouse/grid_scope.duckdb`. The metadata table stores source, retrieved time, checksum, path, HTTP status, and whether normalization succeeded.

- [ ] **Step 4: Verify storage behavior**

Run: `.venv/bin/pytest pipeline/tests/test_connectors.py -v`  
Expected: PASS with no network access.

### Task 4: Add real GISCO and Eurostat connectors

**Files:**
- Create: `pipeline/src/grid_scope/connectors/gisco.py`
- Create: `pipeline/src/grid_scope/connectors/eurostat.py`
- Create: `data/fixtures/gisco-nuts2.geojson`
- Create: `data/fixtures/eurostat-population.json`
- Modify: `pipeline/tests/test_connectors.py`

- [ ] **Step 1: Add mocked contract tests**

Use `respx` fixtures to assert:

- GISCO requests `https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_20M_2024_4326.geojson`.
- Only `LEVL_CODE == 2` features are published.
- Eurostat requests `demo_r_d2jan` with `sex=T`, `age=TOTAL`, and `unit=NR`.
- Eurostat special values remain null with their flags rather than becoming zero.

- [ ] **Step 2: Implement conditional fetches**

Send `If-None-Match` and `If-Modified-Since` when prior metadata exists. Treat HTTP 304 as `cached`; validate content type and minimum feature count before accepting a payload.

- [ ] **Step 3: Normalize GISCO and Eurostat payloads**

GISCO becomes canonical NUTS 2 geometry. Eurostat values join by `geo` code and become contextual observations with their dataset code, unit, time, flags, and retrieval timestamp.

- [ ] **Step 4: Run deterministic and one live smoke test**

Run fixtures: `.venv/bin/pytest pipeline/tests/test_connectors.py -v`  
Expected: PASS.  
Run live: `.venv/bin/python -m grid_scope.cli fetch --only gisco,eurostat --dry-publish`  
Expected: accepted payloads or an explicit cached/failure state without deleting prior data.

### Task 5: Add optional ENTSO-E and curated evidence connectors

**Files:**
- Create: `pipeline/src/grid_scope/connectors/entsoe.py`
- Create: `pipeline/src/grid_scope/connectors/curated.py`
- Create: `data/curated/launch-clusters.json`
- Create: `data/fixtures/entsoe-load.xml`
- Modify: `pipeline/tests/test_connectors.py`

- [ ] **Step 1: Test credential and XML behavior**

Without `ENTSOE_SECURITY_TOKEN`, return `not_configured`. With a token and fixture XML, parse bidding-zone load periods, preserve measurement units, and retain the ENTSO-E document identifier.

- [ ] **Step 2: Define the curated registry schema**

Each launch-cluster record must include canonical entity ID, NUTS relationship, coordinates, phase, capacity and unit where public, date interval, value kind, source tier, URL, publication date, exact claim summary, and analyst review date. JSON schema validation rejects missing source URLs, invented point estimates without a value kind, and Tier D scoring inputs.

- [ ] **Step 3: Populate only verified launch-cluster claims**

Research official planning portals, operator publications, system-operator publications, and reputable corroborating reports for the eight approved launch clusters. Every numerical metric must have at least one source record. Where the evidence does not support a driver, store null and let coverage fall; do not fill a visually convenient value.

- [ ] **Step 4: Add fixture and registry tests**

Run: `.venv/bin/pytest pipeline/tests/test_connectors.py -v`  
Expected: missing token is not an error; malformed XML and unsupported units fail closed; all curated claims validate.

### Task 6: Implement explainable scoring and confidence

**Files:**
- Create: `pipeline/src/grid_scope/scoring.py`
- Create: `pipeline/tests/test_scoring.py`

- [ ] **Step 1: Write failing formula tests**

```python
def test_infrastructure_demand_is_visible_weighted_sum() -> None:
    result = score_infrastructure_demand({
        "compute_load_pressure": 88,
        "connection_scarcity": 84,
        "reinforcement_gap": 80,
        "firm_flexible_supply_gap": 60,
        "cooling_water_stress": 70,
    })
    assert result.score == 78
    assert [c.max_points for c in result.contributions] == [25, 25, 20, 20, 10]
    assert sum(c.points for c in result.contributions) == result.score

def test_missing_is_not_zero_and_can_make_region_unrankable() -> None:
    result = score_infrastructure_demand({"compute_load_pressure": 88})
    assert result.score is None
    assert result.coverage == 25
    assert result.status == "not_yet_rankable"
```

- [ ] **Step 2: Implement fixed-threshold normalization**

Each driver definition contains a unit, floor, ceiling, direction, weight, and model version. Clamp only after recording the raw out-of-range value in the quality report. A score is rankable when weighted coverage is at least 60 and includes compute-load pressure plus at least one grid-constraint driver.

- [ ] **Step 3: Implement separate confidence**

Calculate coverage, source quality, freshness, and agreement separately. The displayed confidence is their documented arithmetic mean rounded to an integer; it never modifies the score.

- [ ] **Step 4: Add supporting-lens tests and implementation**

Site Attractiveness and System Risk return their own contribution arrays, formula versions, coverage, confidence, and nullability. They reuse observations but do not reuse Infrastructure Demand contributions.

- [ ] **Step 5: Run scoring tests**

Run: `.venv/bin/pytest pipeline/tests/test_scoring.py -v`  
Expected: PASS, including boundaries at 0, 100, 59% coverage, and stale/conflicting evidence.

### Task 7: Add quality gates and atomic snapshot publication

**Files:**
- Create: `pipeline/src/grid_scope/quality.py`
- Create: `pipeline/src/grid_scope/publisher.py`
- Create: `pipeline/tests/test_quality.py`
- Create: `pipeline/tests/test_publisher.py`

- [ ] **Step 1: Write publication failure tests**

Test duplicate entity IDs, invalid coordinates, orphan source references, absent active years, score deltas above 25 points without approval, and an interrupted publish. All must leave `web/public/data/latest.json` pointing to the prior snapshot.

- [ ] **Step 2: Implement the quality report**

Return structured errors, warnings, connector summaries, entity counts, rankable counts, null counts, and largest score movements. Errors block publication; warnings publish with manifest annotations.

- [ ] **Step 3: Implement atomic publication**

Write artifacts into `web/public/data/snapshots/<snapshot-id>.tmp`, fsync, rename the directory, then atomically replace `web/public/data/latest.json`. Include checksums for regions, projects, and evidence.

- [ ] **Step 4: Verify last-known-good behavior**

Run: `.venv/bin/pytest pipeline/tests/test_quality.py pipeline/tests/test_publisher.py -v`  
Expected: PASS; no failed test changes the latest pointer.

### Task 8: Build the refresh CLI and checked-in bootstrap snapshot

**Files:**
- Create: `pipeline/src/grid_scope/cli.py`
- Create: `scripts/refresh-snapshot.sh`
- Create: `web/public/data/latest.json`
- Create: `web/public/data/snapshots/bootstrap/*`

- [ ] **Step 1: Implement ordered orchestration**

The CLI performs fetch, capture, normalize, join, score, validate, and publish. `--only`, `--dry-publish`, and `--as-of` support testing. Exit `0` for successful or cached publication, `2` for quality rejection, and `3` when no prior snapshot exists and required geometry cannot be fetched.

- [ ] **Step 2: Add the shell entry point**

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec "$ROOT/.venv/bin/grid-scope-refresh" refresh
```

- [ ] **Step 3: Generate the bootstrap snapshot from verified inputs**

Run: `make refresh`  
Expected: `latest.json` points to an immutable snapshot; the manifest names every connector state and contains no fabricated score.

- [ ] **Step 4: Repeat to prove idempotence**

Run: `make refresh` again.  
Expected: unchanged upstream payloads are cached and either reuse the same content checksums or publish a new run manifest without changing entity values.

### Task 9: Build the Huashu-informed application shell

**Files:**
- Modify: `web/app/layout.tsx`
- Modify: `web/app/globals.css`
- Create: `web/components/opportunity-radar.tsx`
- Create: `web/components/controls/command-bar.tsx`
- Create: `web/components/controls/layer-rail.tsx`
- Create: `web/components/controls/timeline.tsx`
- Create: `web/lib/snapshot/load.ts`
- Create: `web/lib/format.ts`

- [ ] **Step 1: Write a failing shell component test**

Assert that the page shows `GRID//SCOPE`, `Daily refreshed`, the selected year, all three lenses, and snapshot age from a fixture manifest. Assert that it never renders the word `LIVE`.

- [ ] **Step 2: Load IBM Plex fonts and define tokens**

Use `next/font/google` for IBM Plex Sans Condensed, IBM Plex Sans, and IBM Plex Mono. Define the exact tokens from `design/brand-spec.md`; do not introduce additional accent colors or decorative gradients.

- [ ] **Step 3: Implement the rectilinear shell**

Use CSS Grid areas `command`, `layers`, `map`, `inspector`, and `timeline`. Desktop map gets the majority of width. At 768–1099px, layer and inspector panels become controlled overlays. Below 768px, provide a clear desktop-required message plus a compact ranked region list rather than a broken map.

- [ ] **Step 4: Implement state composition**

`OpportunityRadar` owns active lens, year, selected region IDs, visible layers, lifecycle filters, and open drawer. Persist lens/year in URL search parameters; selection remains session state.

- [ ] **Step 5: Run tests**

Run: `cd web && npm test -- opportunity-radar.test.tsx`  
Expected: PASS.

### Task 10: Render the Europe map and data-driven lenses

**Files:**
- Create: `web/components/map/map-style.ts`
- Create: `web/components/map/europe-map.tsx`
- Create: `web/lib/map/expressions.ts`
- Modify: `web/components/opportunity-radar.tsx`

- [ ] **Step 1: Test pure map expressions**

For each lens, assert null/unrankable regions use neutral land, low-to-high values use the approved sequential palette, inherited values expose a pattern flag, and selected regions use the mint outline.

- [ ] **Step 2: Create a dependency-free cartographic base**

Use a MapLibre style with `#07100F` background and no third-party basemap tiles. Add NUTS 2 GeoJSON as fill and line layers, project GeoJSON as clustered/unclustered circle layers, and source-generated country/region labels only when present.

- [ ] **Step 3: Add progressive interaction**

Hover sets feature state and a terse preview. Click selects one region, updates URL-accessible selection state, and performs a bounded camera transition. Shift-click adds regions for comparison. Keyboard users can operate a synchronized ranked list.

- [ ] **Step 4: Add zoom-dependent layers**

Regions appear at Europe scale; project clusters expand at regional zoom; project points and grid context appear only where the snapshot provides coordinates and evidence. No synthetic grid node is drawn.

- [ ] **Step 5: Verify map lifecycle**

Component tests must prove the map instance is created once, event handlers are removed on unmount, source data updates without recreating the map, and lens/year changes update paint properties.

### Task 11: Implement the inspector, evidence dossier, status, and comparison

**Files:**
- Create: `web/components/inspector/region-inspector.tsx`
- Create: `web/components/inspector/evidence-dossier.tsx`
- Create: `web/components/status/data-status-drawer.tsx`
- Create: `web/components/comparison/comparison-drawer.tsx`
- Modify: `web/components/opportunity-radar.tsx`

- [ ] **Step 1: Test truthful uncertainty states**

Assert scoreable, inherited, estimated, stale, conflicting, and not-rankable regions render distinct text and non-color cues. A missing score must render `Not yet rankable`, never `0`.

- [ ] **Step 2: Implement visible score arithmetic**

Render each contribution as `points / max points`; opening a contribution reveals raw value, unit, period, normalization rule, model version, value kind, confidence dimensions, and linked sources.

- [ ] **Step 3: Implement source status**

The command bar shows latest successful snapshot time. The status drawer lists every connector state, last success, last check, and failure message. Cached data remains available with its age.

- [ ] **Step 4: Implement comparison**

Align selected regions by active-year score, five Infrastructure Demand drivers, confidence dimensions, value kinds, and source counts. Do not compare null as zero.

- [ ] **Step 5: Run component tests**

Run: `cd web && npm test`  
Expected: PASS.

### Task 12: Add end-to-end, accessibility, visual, and operations verification

**Files:**
- Create: `web/playwright.config.ts`
- Create: `web/tests/radar.spec.ts`
- Create: `docs/operations/daily-refresh.md`
- Modify: `README.md`

- [ ] **Step 1: Write the browser acceptance flow**

The Playwright test opens the map, selects Frankfurt/Darmstadt from the synchronized region list, changes 2030 to 2031, switches lenses, opens one evidence contribution, adds a second region, opens comparison, and opens the data-status drawer. It asserts URL state, visible labels, and zero page errors.

- [ ] **Step 2: Test failure UI**

Serve a fixture manifest with one failed and one not-configured connector. Assert the map renders from cached data, the global state says `Daily refreshed`, and the drawer explains both connector states.

- [ ] **Step 3: Test keyboard and contrast requirements**

Verify focus reaches command bar, lenses, timeline, ranked region list, inspector contributions, comparison, and source links. Run automated accessibility checks and manually verify 4.5:1 body-text contrast.

- [ ] **Step 4: Capture visual baselines**

Capture 1440×900 desktop and 1024×768 tablet screenshots for demand, risk, dossier, comparison, and source-failure states. Inspect them for panel overflow, unreadable map labels, generic card stacking, and accidental gradients.

- [ ] **Step 5: Document daily operation**

`docs/operations/daily-refresh.md` must show setup, `.env` variables, manual refresh, cron example, snapshot rollback, connector-state interpretation, and how to inspect a rejected quality report.

- [ ] **Step 6: Run the full gate**

Run: `make verify`  
Expected: Python tests pass, web tests pass, Next production build succeeds, browser flows pass, and no console error occurs.

### Task 13: Perform the Huashu design quality review

**Files:**
- Modify as findings require: `web/app/globals.css`
- Modify as findings require: focused `web/components/**`
- Create: `docs/reviews/2026-06-27-huashu-design-review.md`

- [ ] **Step 1: Review five dimensions**

Score philosophy consistency, visual hierarchy, detail execution, functionality, and innovation from 0–10. Record Keep, Fix by severity, and three quick wins.

- [ ] **Step 2: Correct all critical and important findings**

Prioritize map dominance, evidence-trace legibility, non-color uncertainty cues, responsive overflow, and removal of decorative/filler elements.

- [ ] **Step 3: Repeat the browser and visual gate**

Run: `make verify`  
Expected: all tests remain green and refreshed screenshots show no unresolved critical or important review items.

## Plan self-review

- Spec coverage: every section of the approved design maps to Tasks 2–13.
- Truthfulness: optional credentials become `not_configured`; missing evidence becomes null; no task requires fabricated metrics.
- Isolation: upstream connectors terminate at the snapshot publisher; the web app consumes only validated artifacts.
- Type consistency: Python and TypeScript use the same connector states, value kinds, active years, and artifact names.
- Scope: 3D globe, scenarios, alerts, internal data, auth, and public deployment remain excluded.
