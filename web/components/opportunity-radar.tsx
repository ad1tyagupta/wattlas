"use client";

import { useEffect, useMemo, useState } from "react";

import { ComparisonDrawer } from "@/components/comparison/comparison-drawer";
import { CommandBar } from "@/components/controls/command-bar";
import { LayerRail } from "@/components/controls/layer-rail";
import { Timeline } from "@/components/controls/timeline";
import { EvidenceDossier } from "@/components/inspector/evidence-dossier";
import { EntityInspector } from "@/components/inspector/entity-inspector";
import { GlobalMap } from "@/components/map/global-map";
import { DataStatusDrawer } from "@/components/status/data-status-drawer";
import { geographyFeatureCollectionSchema } from "@/lib/snapshot/schema";
import type { AssetFeature, GeographyCollection, GeographyFeature, LensKey, RegionFeature, SnapshotData } from "@/lib/snapshot/types";

type Props = { snapshot: SnapshotData };

export function OpportunityRadar({ snapshot }: Props) {
  const [lens, setLens] = useState<LensKey>("infrastructureDemand");
  const [year, setYear] = useState(2030);
  const initialId = snapshot.countries.features.find((feature) => feature.properties.scores.infrastructureDemand != null)?.properties.id ?? snapshot.countries.features[0]?.properties.id ?? null;
  const [selectedId, setSelectedId] = useState<string | null>(initialId);
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [statusOpen, setStatusOpen] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [admin1, setAdmin1] = useState<GeographyCollection>(snapshot.admin1);
  useEffect(() => {
    if (snapshot.admin1.features.length) return;
    const controller = new AbortController();
    fetch(`/data/${snapshot.manifest.artifacts.admin1}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`ADM1 snapshot request failed: ${response.status}`);
        return response.json();
      })
      .then((payload) => setAdmin1(geographyFeatureCollectionSchema.parse(payload)))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) console.error(error);
      });
    return () => controller.abort();
  }, [snapshot.admin1.features.length, snapshot.manifest.artifacts.admin1]);
  const selectableGeographies = useMemo(
    () => [...snapshot.countries.features, ...admin1.features, ...snapshot.regions.features] as Array<GeographyFeature | RegionFeature>,
    [admin1.features, snapshot.countries.features, snapshot.regions.features],
  );
  const selectedGeography = useMemo(() => selectableGeographies.find((feature) => feature.properties.id === selectedId) ?? null, [selectableGeographies, selectedId]);
  const selectedAsset = useMemo(() => snapshot.assets.features.find((feature) => feature.properties.id === selectedId) as AssetFeature | undefined ?? null, [snapshot.assets.features, selectedId]);
  const comparisonRegions = useMemo(() => comparisonIds.map((id) => selectableGeographies.find((feature) => feature.properties.id === id)).filter(Boolean) as RegionFeature[], [comparisonIds, selectableGeographies]);

  const addComparison = () => {
    if (!selectedId || selectedAsset) return;
    setComparisonIds((current) => current.includes(selectedId) ? current : [...current, selectedId]);
  };

  return (
    <main className="radar-shell">
      <CommandBar manifest={snapshot.manifest} onOpenStatus={() => setStatusOpen(true)} />
      <LayerRail activeLens={lens} onChange={setLens} />
      <GlobalMap countries={snapshot.countries} admin1={admin1} regions={snapshot.regions} assets={snapshot.assets} coverage={snapshot.manifest.coverage} lens={lens} year={year} selectedId={selectedId} onSelect={setSelectedId} />
      <EntityInspector geography={selectedGeography} asset={selectedAsset} lens={lens} year={year} onOpenEvidence={() => setEvidenceOpen(true)} onAddComparison={addComparison} />
      <Timeline years={snapshot.manifest.activeYears} activeYear={year} onChange={setYear} />
      <DataStatusDrawer manifest={snapshot.manifest} open={statusOpen} onClose={() => setStatusOpen(false)} />
      <EvidenceDossier region={selectedGeography as RegionFeature | null} evidence={snapshot.evidence} open={evidenceOpen && !selectedAsset} onClose={() => setEvidenceOpen(false)} />
      <ComparisonDrawer regions={comparisonRegions} lens={lens} year={year} onClose={() => setComparisonIds([])} onRemove={(id) => setComparisonIds((current) => current.filter((item) => item !== id))} />
      {comparisonIds.length === 1 && <div className="comparison-toast">1 region queued. Select another region and add it to compare.<button type="button" onClick={() => setComparisonIds([])}>Clear</button></div>}
    </main>
  );
}
