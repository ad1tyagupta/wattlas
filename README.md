# Wattlas

Wattlas is a global Opportunity Radar for examining where data-centre and water-infrastructure growth may create electricity demand, opportunity, or constraint from 2026–2031.

The working version combines a clustered global MapLibre map, strong national boundaries, 334 European NUTS-2 regions, an explainable Infrastructure Demand score, supporting Site Attractiveness and System Risk lenses, facility provenance, source status, evidence dossiers, and regional comparison.

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

The global release uses UN national boundaries, GISCO/Eurostat regional context, curated official project evidence, and community-maintained OpenStreetMap infrastructure queried through QLever. Snapshot `2026-06-27T17-11-15Z` contains 3,634 mapped facilities: 3,533 data centres and 101 water-infrastructure assets across 112 countries. OpenStreetMap-derived records are attributed under ODbL and visibly labelled `community_mapped`; curated announcements are labelled `official_verified`. Missing evidence is stored as `null`, never as zero.

## Data caution

Operational community-mapped facilities provide context and counts only. They do not create future demand MW. Opportunity scores are provisional analyst indices derived only from forward-looking, demand-backed public evidence; they are not observed regional grid measurements.
