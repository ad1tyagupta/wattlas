# Wattlas Global Facility Coverage Design

**Status:** Approved on 2026-06-27

## Objective

Replace the 14-record sample-only global infrastructure layer with broad, daily refreshed public facility coverage while preserving Wattlas's evidence standards and explainable 2026–2031 scoring model.

## Validated constraints

- Public data only.
- Global country coverage with progressively revealed subnational detail.
- Infrastructure Demand remains the primary score; Site Attractiveness and System Risk remain supporting lenses.
- Operational infrastructure provides context. Only forward-looking projects with demand evidence contribute to the opportunity score.
- Community-maintained OpenStreetMap records may appear alongside official records when their provenance is clearly distinguished.
- The interface must never invent facility capacity, lifecycle, location precision, or source confidence.
- Data remains daily refreshed with immutable snapshots and last-known-good fallback.

## Selected approach

Use QLever's public OpenStreetMap planet endpoint as the scalable global facility feed and merge its records with Wattlas's curated official project registry. Do not use PeeringDB as the default source because its acceptable-use restrictions are unsuitable for Wattlas's potential commercial use. Do not process the full OSM planet locally because that would make daily refreshes unnecessarily expensive.

The first expanded release will ingest:

- operational data centres tagged `telecom=data_center`;
- construction and proposed data centres represented by supported OSM lifecycle tags;
- desalination plants tagged `water_works=desalination` or `man_made=desalination_plant`;
- existing curated Wattlas data-centre and water projects, which remain the higher-confidence source when records overlap.

## Data flow

1. Query QLever for supported OSM tags, geometry, name, operator, lifecycle signals, dates, and relevant source metadata.
2. Convert point and polygon geometry into representative display coordinates without fabricating site precision.
3. Assign every record to a UN country boundary and, where available, a reliable subnational geography.
4. Normalize records into the Wattlas asset contract.
5. Deduplicate by stable external ID first, then by strong operator/name/proximity agreement. Preserve separate buildings when campus membership is uncertain.
6. Merge community records with curated official projects, preferring official lifecycle, capacity, coordinates, and evidence when the two sources describe the same asset.
7. Validate counts, coordinates, IDs, country assignment, lifecycle values, and provenance before publication.
8. Publish the validated snapshot and retain the previous snapshot if the connector fails or coverage collapses.

## Provenance and quality

Every asset will expose:

- `sourceType`: `community_mapped` or `official_verified`;
- source URL and stable external ID;
- operator and facility name when present;
- lifecycle and lifecycle evidence;
- location precision;
- last-observed timestamp;
- MW range only when publicly reported or transparently estimated under an approved assumption.

Unnamed OSM records remain usable and receive deterministic labels such as `Mapped data centre · OSM 12345`. Community records do not inherit official verification. Missing capacity remains unavailable.

The global OSM connector must publish at least 3,500 data-centre records. A lower count is treated as an invalid or partial response and triggers last-known-good fallback. All published IDs must be unique, coordinates valid, and country assignments recognized.

## Scoring rules

Operational facilities are visible context and contribute to counts, density, and market-presence summaries. They do not add speculative future MW to Infrastructure Demand.

Only announced, planning-filed, permitted, or under-construction projects with demand evidence can contribute to 2026–2031 demand scores. Community-mapped lifecycle signals may describe status but do not create demand MW. Category-specific and combined scores remain separate and explainable.

## Map and inspection experience

- Cluster thousands of records at global zoom and display the number of facilities in each cluster.
- Expand clusters progressively until individual facilities become selectable.
- Use periwinkle for data centres and mint for water infrastructure.
- Visually distinguish operational versus forward-looking assets and community-mapped versus officially verified provenance.
- Selecting an asset shows its name, operator, lifecycle, provenance, location precision, source link, observation date, and MW range when available.
- Country inspection shows total, operational, planned, data-centre, water, official, and community-mapped counts.
- Preserve national boundaries, country choropleths, analytical lenses, and the 2026–2031 timeline.

## Failure handling

- Capture raw QLever responses and retain immutable canonical snapshots.
- Retry transient connector failures conservatively.
- Reject malformed, duplicate, geographically invalid, or unexpectedly small responses.
- Serve the last validated facility snapshot when QLever or another connector fails.
- Expose connector freshness and stale state in the existing data-status experience.

## Verification

Automated coverage will include connector parsing, geometry conversion, country assignment, deduplication, official-source precedence, scoring isolation, minimum-count validation, stale fallback, snapshot publication, schema loading, map clustering, asset selection, country summaries, and production rendering.

Acceptance requires:

- at least 3,500 published data-centre records;
- supported desalination records plus curated water projects;
- no operational record creating future demand MW;
- successful Python tests, web tests, lint, production build, and end-to-end browser tests;
- a clean production browser render with the published facility count visible and no console or page errors.
