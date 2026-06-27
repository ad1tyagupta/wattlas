# Wattlas

Wattlas is a global Opportunity Radar for examining where data-centre and water-infrastructure growth may create electricity demand, opportunity, or constraint from 2026–2031.

The working version combines a MapLibre NUTS-2 map, an explainable Infrastructure Demand score, supporting Site Attractiveness and System Risk lenses, confidence and coverage, source status, evidence dossiers, and regional comparison.

## Run locally

Requirements: Python 3.13 and Node.js 22.

```bash
make setup
make refresh
make dev
```

Open `http://127.0.0.1:3000`.

## Verify

```bash
make test
cd web && npm run build
```

## Daily data model

The browser never queries upstream sources directly. The Python pipeline fetches public sources, validates and scores them, and atomically publishes an immutable JSON/GeoJSON snapshot. The interface always reads `web/public/data/latest.json`, so a connector failure does not erase the last useful map.

A local Codex automation is active once per day at 04:00 Europe/Berlin. The repository also includes a GitHub Actions alternative that keeps the same Berlin schedule across daylight-saving changes; once the repository is Git-connected, a hosted deployment can rebuild from each committed snapshot. The app deliberately says **Daily refreshed**, not “live”.

The implemented Europe-first slice currently uses GISCO NUTS-2 geometry, Eurostat population, and eight analyst-curated launch clusters. The approved global migration uses UN national boundaries, available UN SALB subnational geometry, and public infrastructure evidence. Missing evidence is stored as `null`, never as zero.

## Data caution

Launch-cluster scores are provisional analyst indices derived from cited public signals. They are estimates, not observed regional grid measurements. The evidence drawer exposes the attached public sources and the interface keeps confidence separate from score.
