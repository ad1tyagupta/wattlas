"use client";

import { useEffect, useState } from "react";

import { OpportunityRadar } from "@/components/opportunity-radar";
import { loadSnapshotFromStaticAssets } from "@/lib/snapshot/client-load";
import type { SnapshotData } from "@/lib/snapshot/types";

export function SnapshotLoader() {
  const [snapshot, setSnapshot] = useState<SnapshotData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void loadSnapshotFromStaticAssets(controller.signal)
      .then(setSnapshot)
      .catch((loadError: unknown) => {
        if (loadError instanceof DOMException && loadError.name === "AbortError") return;
        setError(loadError instanceof Error ? loadError.message : "Unable to load Wattlas data snapshot.");
      });
    return () => controller.abort();
  }, []);

  if (snapshot) return <OpportunityRadar snapshot={snapshot} />;

  return (
    <main className="snapshot-loader" aria-busy={!error} aria-live="polite">
      <section className="snapshot-loader-card">
        <p className="eyebrow">WATTLAS</p>
        <h1>{error ? "Data snapshot unavailable" : "Loading global infrastructure map"}</h1>
        <p>
          {error
            ? "The app shell loaded, but the latest static data snapshot could not be read."
            : "Fetching the latest country, state, infrastructure, and evidence layers from the static data CDN."}
        </p>
        {error ? <pre>{error}</pre> : <div className="snapshot-loader-bar" aria-hidden="true" />}
      </section>
    </main>
  );
}
