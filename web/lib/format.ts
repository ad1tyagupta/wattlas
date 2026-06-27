export function formatSnapshotTime(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(value));
}

export function formatPopulation(value?: number | null): string {
  if (value == null) return "Regional population unavailable";
  return `${new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value)} residents`;
}

export function connectorLabel(id: string): string {
  return {
    gisco: "GISCO boundaries",
    eurostat: "Eurostat regional context",
    curated_evidence: "Curated project evidence",
    entsoe: "ENTSO-E electricity data",
  }[id] ?? id;
}
