# Wattlas web application

This Next.js application renders the Wattlas global Opportunity Radar from immutable JSON and GeoJSON snapshots published by the Python pipeline.

## Run locally

```bash
npm install
npm run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000).

The browser does not fetch upstream infrastructure sources directly. It reads the latest validated public snapshot and continues serving the last successful version when a connector fails.

## Verify

```bash
npm test
npm run lint
npm run build
```

The production build is intended for a Git-connected Vercel project after the Wattlas repository is created.
