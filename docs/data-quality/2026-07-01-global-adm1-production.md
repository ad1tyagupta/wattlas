# Global ADM1 production coverage — 2026-07-01

This report records the version-pinned population and regional-demand inputs used by the Wattlas production refresh. Missing population is never converted to zero and no regional demand share is fabricated.

## Coverage

- Boundaries: 3,229 active ADM1 geographies in 197 countries.
- Population: 19,224 records for 3,204 geographies across 2026–2031.
- Primary source: WorldPop Global2 R2025A v1, 2025 constrained UN-adjusted population count raster at 30 arc-seconds (approximately 1 km).
- High-resolution fallback: official WorldPop R2025A v1 2025 constrained country rasters at 3 arc-seconds (approximately 100 m), attempted only for primary-raster gaps and pinned by URL and SHA-256 checksum.
- Fallback rescues: 23 geographies / 138 annual records. Primary records are never overwritten.
- Remaining unavailable: 25 geographies / 150 annual markers. These remain unavailable, not zero.
- Regional demand weights: 18,444 records for 3,074 rankable geographies.
- Country-level-only exceptions: 11 countries containing 155 ADM1 boundaries. Their boundaries remain selectable, but none of their ADM1 regions receives a modelled population share, demand allocation, or Power Balance rank.
- India: all 36 required states and union territories have population coverage, including Jammu and Kashmir, Ladakh, Assam, and Arunachal Pradesh.

## Country-level-only exceptions

| Country | Active ADM1 | Unsupported ADM1 |
|---|---:|---|
| Antigua and Barbuda (AG) | 8 | Redonda |
| Bahamas (BS) | 32 | Moore's Island |
| Greenland (GL) | 6 | Northeast Greenland National Park |
| Equatorial Guinea (GQ) | 7 | Annobón |
| Marshall Islands (MH) | 24 | Kili; Rongelap |
| Mauritius (MU) | 12 | Agaléga; St. Brandon |
| Namibia (NA) | 14 | Cunene |
| Nauru (NR) | 14 | Meneng; Yaren |
| Niue (NU) | 14 | Avatele; Liku; Makefu; Mutalau; Namukulu; Tamakautoga; Toi; Tuapa |
| Palau (PW) | 16 | Hatohobei; Ngardmau; Sonsorol |
| Tuvalu (TV) | 8 | Nui; Nukufetau; Nukulaelae |

The exception is applied to the whole country because allocating the national electricity control across only the covered subset would overstate those regions. Wattlas publishes the national control alongside explicit unavailable ADM1 energy rows instead.

## Integrity and limitations

- Population build fingerprint: `sha256:8cff873bdd5537b521964fe6fe536b8d81f06aa18140d6714eb1cfab99913c92`.
- Demand-weight build fingerprint: `sha256:05b2984921d1cea70e18382d7c4c2d03d1ce1e9ee759f277f4173bcce597bfa8`.
- Compact artifact sizes: 8,586,903 bytes population; 4,018,061 bytes demand weights.
- The 2025 source raster is carried forward unchanged for 2026–2031 and explicitly labelled `worldpop-carry-forward-v1`; Wattlas does not imply observed annual population growth.
- Country 100 m rasters use a different national boundary mastergrid than Wattlas ADM1 boundaries. Coverage remains fail-closed when a boundary exceeds the source raster by more than 0.001 pixel.
- The global raster's serialized +180° edge is approximately 0.00017 pixel short. A tested sub-0.001-pixel tolerance treats that numerical drift as full coverage while continuing to reject real clipping.

## Published electricity and generation snapshot

- Snapshot: `2026-07-01T10-38-09Z`, generated `2026-07-01T10:38:09Z` with model `2.1.0`.
- Ember release: `yearly_full_release_long_format.csv`, last modified 2026-06-23 10:58:24 GMT, from `https://files.ember-energy.org/public-downloads/yearly_full_release_long_format.csv` under CC BY 4.0.
- Ember release size and checksum: 49,079,981 bytes; SHA-256 `259e1095ee8ffeaf0aff37ad557916ae1823a2da13312da50ba4cec6b4574c3b`.
- Country controls: 5,388 annual records for 214 countries/economies, spanning 2000–2025; the published connector observation date is 2025-12-31.
- Regional energy: 3,185 ADM1 time series / 19,110 annual rows for 2026–2031. This comprises 3,030 modelled regions, including 1,895 Power Balance-rankable regions and 1,135 not-yet-rankable regions, plus 155 explicit country-level-only regions.
- Power generation: 55,895 public OSM source records canonicalized to 55,895 plants; 53,252 plants with valid active ADM1 placement are published across 2,086 ADM1 regions. Generator IDs are unique and country-shard totals reconcile exactly.
- Demand facilities: 4,325 total, comprising 4,224 data centres and 101 water-infrastructure facilities.
- Reconciliation gates passed: country demand, generator artifacts, artifact checksums, duplicate generator IDs, and all per-artifact size limits.
- Regional-energy v2 stores five invariant score-contribution definitions once and reconstructs the complete UI contract at load time. The production artifact is 34,875,250 bytes, below the 50,000,000-byte hard guard (and below the 40 MB design target).
- India validation includes all 36 states and union territories, specifically Jammu and Kashmir, Ladakh, Assam, and Arunachal Pradesh.

### Limitations

- GEM, WRI, optional official power releases, EIA state observations, and ENTSO-E were not configured for this public-only refresh. Power-plant coverage in this snapshot therefore comes from community-maintained OpenStreetMap and is labelled accordingly.
- Regional demand is an allocation of the latest available country control, carried as a flat baseline before separately sourced 2026–2031 infrastructure increments. It is not a claim of observed ADM1 electricity consumption.
- A Power Balance rank requires adequate public supply evidence. Modelled demand without sufficient local generation coverage remains visible but not rankable; it is never converted into a claimed deficit.
