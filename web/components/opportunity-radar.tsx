"use client";

import { useMemo, useState } from "react";

import { ComparisonDrawer } from "@/components/comparison/comparison-drawer";
import { CommandBar } from "@/components/controls/command-bar";
import { LayerRail } from "@/components/controls/layer-rail";
import { Timeline } from "@/components/controls/timeline";
import { EvidenceDossier } from "@/components/inspector/evidence-dossier";
import { RegionInspector } from "@/components/inspector/region-inspector";
import { EuropeMap } from "@/components/map/europe-map";
import { DataStatusDrawer } from "@/components/status/data-status-drawer";
import type { LensKey, RegionFeature, SnapshotData } from "@/lib/snapshot/types";

type Props = { snapshot: SnapshotData };

export function OpportunityRadar({ snapshot }: Props) {
  const [lens, setLens] = useState<LensKey>("infrastructureDemand");
  const [year, setYear] = useState(2030);
  const initialId = snapshot.regions.features.find((feature) => feature.properties.scores.infrastructureDemand != null)?.properties.id ?? null;
  const [selectedId, setSelectedId] = useState<string | null>(initialId);
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [statusOpen, setStatusOpen] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const selectedRegion = useMemo(() => snapshot.regions.features.find((feature) => feature.properties.id === selectedId) as RegionFeature | undefined ?? null, [snapshot.regions.features, selectedId]);
  const comparisonRegions = useMemo(() => comparisonIds.map((id) => snapshot.regions.features.find((feature) => feature.properties.id === id)).filter(Boolean) as RegionFeature[], [comparisonIds, snapshot.regions.features]);

  const addComparison = () => {
    if (!selectedId) return;
    setComparisonIds((current) => current.includes(selectedId) ? current : [...current, selectedId]);
  };

  return (
    <main className="radar-shell">
      <CommandBar manifest={snapshot.manifest} onOpenStatus={() => setStatusOpen(true)} />
      <LayerRail activeLens={lens} onChange={setLens} />
      <EuropeMap regions={snapshot.regions} projects={snapshot.projects} lens={lens} year={year} selectedId={selectedId} onSelect={setSelectedId} />
      <RegionInspector region={selectedRegion} lens={lens} year={year} onOpenEvidence={() => setEvidenceOpen(true)} onAddComparison={addComparison} />
      <Timeline years={snapshot.manifest.activeYears} activeYear={year} onChange={setYear} />
      <DataStatusDrawer manifest={snapshot.manifest} open={statusOpen} onClose={() => setStatusOpen(false)} />
      <EvidenceDossier region={selectedRegion} evidence={snapshot.evidence} open={evidenceOpen} onClose={() => setEvidenceOpen(false)} />
      <ComparisonDrawer regions={comparisonRegions} lens={lens} year={year} onClose={() => setComparisonIds([])} onRemove={(id) => setComparisonIds((current) => current.filter((item) => item !== id))} />
      {comparisonIds.length === 1 && <div className="comparison-toast">1 region queued. Select another region and add it to compare.<button type="button" onClick={() => setComparisonIds([])}>Clear</button></div>}
    </main>
  );
}
