from __future__ import annotations


def normalize_ember_rows(
    rows: list[dict[str, str]], *, country_lookup: dict[str, str] | None = None
) -> list[dict]:
    lookup = country_lookup or {}
    normalized: list[dict] = []
    for row in rows:
        iso3 = (row.get("Country code") or "").strip() or lookup.get(
            (row.get("Country") or "").strip()
        )
        if not iso3:
            continue
        raw_value = (row.get("Value") or "").strip()
        normalized.append(
            {
                "countryIso3": iso3,
                "value": float(raw_value) if raw_value else None,
            }
        )
    return normalized
