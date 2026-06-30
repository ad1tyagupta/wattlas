const LEGACY_CONTRIBUTION_MODEL_VERSIONS = new Set(["2.1.0"]);

export function migrateLegacyContributions<T>(payload: T, modelVersion: string, enabled: boolean): T {
  if (!enabled || !LEGACY_CONTRIBUTION_MODEL_VERSIONS.has(modelVersion)) return payload;
  const visit = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value) visit(item);
      return;
    }
    if (value === null || typeof value !== "object") return;
    const record = value as Record<string, unknown>;
    if (
      typeof record.id === "string" && typeof record.label === "string"
      && "points" in record && typeof record.normalization === "string"
      && !("methodVersion" in record)
    ) record.methodVersion = `legacy-${modelVersion}`;
    for (const child of Object.values(record)) visit(child);
  };
  visit(payload);
  return payload;
}
