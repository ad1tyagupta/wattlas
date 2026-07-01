# Wattlas

Wattlas is a global Opportunity Radar for examining where data-centre and water-infrastructure growth may create electricity demand, opportunity, or constraint from 2026–2031.

The working version combines a clustered global MapLibre map, strong national boundaries, 3,229 global ADM1 states/provinces, 334 European NUTS-2 regions, an explainable Infrastructure Demand score, supporting Site Attractiveness and System Risk lenses, rich facility provenance, source status, evidence dossiers, and regional comparison.

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

The global release uses UN national boundaries, geoBoundaries `gbOpen` ADM1 regions, GISCO/Eurostat European context, curated official project evidence, and community-maintained OpenStreetMap infrastructure queried through QLever. India uses the explicitly attributed Government of India boundary perspective; Jammu and Kashmir, Ladakh, Assam, and Arunachal Pradesh are included in the validation gate.

Regional population uses the checksum-pinned WorldPop Global2 R2025A v1 2025 constrained 1 km raster, with official 100 m country rasters used only for otherwise unavailable tiny regions. The production build covers 3,204 of 3,229 ADM1 geographies. The remaining 25 gaps place 11 countries in an explicit country-level-only mode: all boundaries remain selectable, national electricity controls may be shown, but no ADM1 demand share or Power Balance rank is fabricated. Exact coverage and fingerprints are recorded in `docs/data-quality/2026-07-01-global-adm1-production.md`.

Snapshot `2026-07-01T10-38-09Z` contains 3,229 global ADM1 regions across 197 countries, 4,325 demand facilities (4,224 data centres and 101 water-infrastructure assets), and 53,252 deduplicated power generators. Ember's 2026-06-23 public Yearly Electricity Data release supplies 5,388 annual country controls across 214 countries/economies; 3,030 ADM1 regions receive modelled 2026–2031 energy rows, of which 1,895 are currently Power Balance-rankable. OpenStreetMap-derived records are attributed under ODbL and visibly labelled `community_mapped`; curated announcements are labelled `official_verified`. Missing evidence is stored as `null`, never as zero.

Facility details expose all available public identity, address, operational, energy, and source fields. A reported electrical tag remains separate from Wattlas demand estimates; missing capacity is never inferred.

## Data caution

Operational community-mapped facilities provide context and counts only. They do not create future demand MW. Opportunity scores are provisional analyst indices derived only from forward-looking, demand-backed public evidence; they are not observed regional grid measurements.
