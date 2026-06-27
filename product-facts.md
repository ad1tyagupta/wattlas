# Product and technology facts

> Verified: 2026-06-27. This file records facts that affect the implementation so they are not inferred from memory.

## Product boundary

- The product is a new, independent global energy and infrastructure Opportunity Radar whose validated foundation was Europe-first.
- “Palantir - My Ver” is the workspace name and inspiration context, not permission to use Palantir branding, logos, or proprietary assets.
- `Wattlas` is the approved product name. `GRID//SCOPE` is retained only in historical design artifacts.

## Map rendering

- MapLibre GL JS is an open-source TypeScript library that renders interactive vector-tile maps in the browser with WebGL.
- Its official documentation currently demonstrates the `5.12` package line and supports data-driven styles, sources, markers, controls, globe projection, clustering, and custom layers.
- The first version will use the 2D map projection. Globe mode remains a later briefing capability.
- Sources:
  - https://maplibre.org/maplibre-gl-js/docs
  - https://maplibre.org/projects/gl-js/

## Web application

- Next.js App Router remains the current official application architecture in the March 2026 documentation.
- The App Router supports Server Components, client components, layouts, routing, and backend-for-frontend patterns.
- Source: https://nextjs.org/docs/app

## Analytical storage

- DuckDB 1.5 is the current documentation line as of this verification date.
- DuckDB 1.5.4 was released on 2026-06-17 according to the official release calendar.
- DuckDB supports Parquet, JSON, spatial processing through its spatial extension, and a built-in `GEOMETRY` type in the 1.5 line.
- Sources:
  - https://duckdb.org/docs/stable/
  - https://duckdb.org/release_calendar
  - https://duckdb.org/docs/current/core_extensions/spatial/overview

## Public-data facts

- ENTSO-E Transparency Platform publishes European electricity-market information including generation, load, transmission, and balancing. API access requires an access token; the product must operate from the last successful snapshot when a token is absent or a pull fails.
- Capacitypedia is a navigation layer for publicly available hosting-capacity information contributed voluntarily by participating TSOs and DSOs. It is not a complete, uniform Europe-wide capacity API.
- ERA5 provides hourly reanalysis variables from 1940 onward. It is appropriate for historical heat, wind, solar, and climate-stress baselines, not a real-time operational weather feed.
- Eurostat exposes free REST/SDMX APIs and GISCO distributes NUTS geometries. Eurostat’s public database exposes the latest dataset version rather than a complete revision history, so the Opportunity Radar must retain its own immutable snapshots.
- EU data-centre energy-performance reporting provides useful aggregated outputs, but it does not replace a curated site/project evidence registry.
- OpenStreetMap currently contains more than 4,200 objects tagged `telecom=data_center`; Wattlas queries the OSM planet through QLever and publishes only records that can be assigned to its UN country geometry.
- OSM infrastructure is community-maintained and licensed under ODbL. Wattlas preserves attribution, stable OSM element URLs, source type, and observation date.
- QLever's OSM planet index is based on weekly planet processing and may lag the primary OSM database. Wattlas still checks the connector daily and retains its last validated capture when the query fails or falls below the minimum coverage threshold.
- PeeringDB is not used as a default facility feed because its acceptable-use restrictions are not suitable for Wattlas's potential commercial use.
- Sources:
  - https://www.entsoe.eu/data/transparency-platform/
  - https://www.entsoe.eu/news/2026/05/22/entso-e-and-dso-entity-launched-capacitypedia-to-improve-access-to-grid-hosting-capacity-information-across-europe/
  - https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=overview
  - https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-getting-started
  - https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics
  - https://energy.ec.europa.eu/topics/energy-efficiency/energy-efficiency-targets-directive-and-rules/energy-efficiency-directive/energy-performance-data-centres_en
  - https://wiki.openstreetmap.org/wiki/Tag:telecom%3Ddata_center
  - https://www.openstreetmap.org/copyright
  - https://qlever.dev/osm-planet

## Truthfulness constraint

- A value may be labelled `observed`, `reported`, `estimated`, `inherited`, or `unavailable`.
- A connector’s absence may never be disguised as a live value.
- The interface must display both the latest successful product snapshot and the freshness/status of each contributing source.
