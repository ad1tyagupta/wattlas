# Wattlas web application

This Next.js application renders the Wattlas global Opportunity Radar from immutable JSON and GeoJSON snapshots published by the Python pipeline.

## Run locally

```bash
npm install
npm run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000).

The browser does not fetch upstream infrastructure sources directly. It reads the latest validated public snapshot and continues serving the last successful version when a connector fails.

The current snapshot includes more than 3,500 data-centre records sourced from OpenStreetMap through QLever. Global markers are clustered at low zoom and individual facilities expose lifecycle, operator, location precision, official/community provenance, and their public source record.

## Verify

```bash
npm test
npm run lint
npm run build
```

Production is deployed from the Git-connected `ad1tyagupta/wattlas` repository to `https://wattlas.vercel.app`.
