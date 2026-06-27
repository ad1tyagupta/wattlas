# Wattlas Global Regions and Facility Details Design

**Status:** Approved on 2026-06-28

## Objective

Add useful first-level administrative boundaries and regional intelligence outside Europe, render India from the Government of India boundary perspective, and substantially enrich every mapped infrastructure facility with all available public attributes.

## Validated product constraints

- Wattlas remains global, public-data-only, daily refreshed, and evidence-first.
- Infrastructure Demand remains the primary score; Site Attractiveness and System Risk remain supporting lenses.
- The 2026–2031 horizon and explainable score arithmetic remain unchanged.
- Operational infrastructure is contextual. Only forward-looking, demand-backed projects affect opportunity scores.
- Missing information remains explicitly unavailable and is never inferred.
- Community-maintained and officially verified records remain visibly distinct.

## Boundary sources and perspective

Use geoBoundaries `gbOpen` first-level administrative boundaries as the global ADM1 source. The dataset is CC-BY 4.0 and provides state/province/region coverage for 199 countries. Cache a pinned release and refresh only when upstream boundary metadata changes; administrative geometry does not need a full daily network refresh.

Retain GISCO NUTS-2 boundaries as a deeper European layer. The resulting hierarchy is:

1. National boundaries at every supported zoom.
2. Global ADM1 states/provinces from medium zoom.
3. European NUTS-2 regions at closer zoom.

### India exception

Replace the UN India outline with a Government of India boundary perspective sourced from an official Government of India open administrative-boundary dataset where technically reusable. Use the same perspective for India's ADM1 states and union territories.

The India validation gate must confirm all 28 states and 8 union territories and must explicitly confirm:

- Jammu and Kashmir;
- Ladakh;
- Assam;
- Arunachal Pradesh.

The interface must display `India boundary perspective: Government of India` in map attribution and source status. This is a declared cartographic source choice, not an attempt to hide the existence of territorial disputes.

## Boundary processing

Normalize all ADM1 records into stable Wattlas geography IDs, ISO country codes, names, source IDs, parent-country IDs, geometry, and source metadata. Simplify geometry to a browser-safe resolution while preserving topology well enough for analytical selection.

Validate:

- expected country and ADM1 coverage;
- unique geography IDs;
- Polygon or MultiPolygon geometry;
- recognized parent countries;
- non-empty names and source attribution;
- required Indian states and union territories;
- no accidental use of the UN India outline after the India override.

If a refresh fails or coverage drops unexpectedly, retain the last validated boundaries.

## Regional intelligence

Assign every facility point to the most specific available region. Country and region records expose:

- total facilities;
- operational and planned facilities;
- data-centre and water-infrastructure counts;
- officially verified and community-mapped counts;
- low/base/high demand MW when demand-backed projects exist;
- explainable lens scores, contributions, confidence, coverage, dates, and source IDs.

Regions containing only operational or uncited infrastructure remain selectable but unranked.

## Facility enrichment

Extend the QLever/OpenStreetMap query and asset contract to preserve all available public fields:

- name, operator, and owner;
- website;
- facility/operator reference;
- street, house number, city, state, postcode, and country address tags;
- start and opening dates;
- lifecycle and category;
- exact coordinates or labelled location precision;
- reported electrical input or data-centre power where explicitly tagged;
- OSM, Wikidata, and Wikipedia identifiers/links;
- source URL, source type, licence, and last-observed date;
- low/base/high demand MW only when reported or attached to an approved Wattlas assumption.

The facility inspector groups fields into Identity, Location, Operations, Energy, and Sources. Empty groups are not fabricated; individual unavailable values are labelled clearly.

## Map interaction

- Keep national boundaries visually strongest.
- Show ADM1 boundaries from medium zoom and European NUTS-2 boundaries at closer zoom.
- Preserve clustered infrastructure markers at world scale.
- Selecting an ADM1 geography opens regional counts and explainable scores.
- Selecting a facility opens the expanded grouped detail panel and direct public source links.
- Preserve periwinkle data-centre markers, mint water markers, and amber clusters.
- Add explicit geoBoundaries, Government of India, United Nations, GISCO, and OpenStreetMap attribution as applicable.

## Performance

Publish simplified ADM1 geometry as its own immutable snapshot artifact. Load it with the existing server-rendered snapshot, but render only appropriate layers by zoom. Keep clustering enabled for the expanded asset collection. Set size and feature-count guardrails so a bad boundary response cannot create an unusable deployment.

## Verification

Automated tests must cover:

- geoBoundaries metadata and geometry parsing;
- global ADM1 coverage and stable IDs;
- India outline override and required India regions, including Arunachal Pradesh;
- point-to-region assignment and regional summaries;
- regional scoring isolation for operational assets;
- enriched OSM facility fields and unavailable states;
- schema loading and immutable snapshot publication;
- map layer zoom hierarchy and boundary styling;
- geography and facility selection;
- desktop and narrow-pane rendering;
- production data counts, attribution, and zero browser errors.

Completion requires full Python, Vitest, lint, Next.js build, Playwright, local browser, GitHub, Vercel, and clean production-browser verification.
