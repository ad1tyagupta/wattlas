import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mapCalls = vi.hoisted(() => ({
  sources: [] as Array<[string, Record<string, unknown>]>,
  layers: [] as Array<Record<string, unknown>>,
  handlers: [] as Array<[string, unknown, unknown?]>,
  featureStates: [] as Array<Record<string, unknown>>,
}));

vi.mock("maplibre-gl", () => ({
  default: {
    Map: class {
      addControl() {}
      addSource(id: string, source: Record<string, unknown>) { mapCalls.sources.push([id, source]); }
      addLayer(layer: Record<string, unknown>) { mapCalls.layers.push(layer); }
      getCanvas() { return { style: { cursor: "" } }; }
      getLayer() { return undefined; }
      getSource() { return undefined; }
      isStyleLoaded() { return false; }
      on(event: string, layerOrHandler: unknown, handler?: unknown) {
        mapCalls.handlers.push([event, layerOrHandler, handler]);
        if (event === "load" && typeof layerOrHandler === "function") layerOrHandler();
      }
      setFeatureState(target: Record<string, unknown>, state: Record<string, unknown>) { mapCalls.featureStates.push({ target, state }); }
      remove() {}
      setPaintProperty() {}
    },
    NavigationControl: class {},
    AttributionControl: class {},
  },
}));

import { GLOBAL_VIEW, GlobalMap } from "@/components/map/global-map";
import type { AssetCollection, GeographyCollection } from "@/lib/snapshot/types";

describe("GlobalMap", () => {
  beforeEach(() => {
    mapCalls.sources.length = 0;
    mapCalls.layers.length = 0;
    mapCalls.handlers.length = 0;
    mapCalls.featureStates.length = 0;
  });

  it("opens at world scale and reports global coverage", () => {
    render(
      <GlobalMap
        countries={{ type: "FeatureCollection", features: [] }}
        admin1={{ type: "FeatureCollection", features: [] }}
        regions={{ type: "FeatureCollection", features: [] }}
        assets={{ type: "FeatureCollection", features: [] }}
        lens="infrastructureDemand"
        year={2030}
        selectedId={null}
        onSelect={() => undefined}
        coverage={{ countries: 246, regions: 334, admin1Regions: 3229, countriesWithAdmin1: 197, assets: 14, dataCentres: 8, waterInfrastructure: 6 }}
      />,
    );

    expect(GLOBAL_VIEW.zoom).toBeLessThan(2);
    expect(screen.getByRole("region", { name: "Global opportunity map" })).toBeInTheDocument();
    expect(screen.getByText(/246 countries · 14 infrastructure assets/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "OpenStreetMap infrastructure attribution" })).toHaveAttribute("href", "https://www.openstreetmap.org/copyright");
    expect(screen.getByText(/India boundary perspective: Government of India/i)).toBeInTheDocument();
  });

  it("clusters infrastructure while preserving selectable facility layers", () => {
    render(
      <GlobalMap
        countries={{ type: "FeatureCollection", features: [] }}
        admin1={{ type: "FeatureCollection", features: [] }}
        regions={{ type: "FeatureCollection", features: [] }}
        assets={{ type: "FeatureCollection", features: [] }}
        lens="infrastructureDemand"
        year={2030}
        selectedId={null}
        onSelect={() => undefined}
        coverage={{ countries: 246, regions: 334, admin1Regions: 3229, countriesWithAdmin1: 197, assets: 4395, dataCentres: 4265, waterInfrastructure: 130 }}
      />,
    );

    const assetSource = mapCalls.sources.find(([id]) => id === "assets")?.[1];
    expect(assetSource).toMatchObject({ cluster: true, clusterRadius: 48, clusterMaxZoom: 6 });
    expect(mapCalls.layers.map((layer) => layer.id)).toEqual(expect.arrayContaining([
      "asset-clusters",
      "asset-cluster-count",
      "data-centre-assets",
      "water-assets",
    ]));
  });

  it("renders overview and technology generators with neutral composition-aware clusters", () => {
    render(
      <GlobalMap countries={{ type: "FeatureCollection", features: [] }} admin1={{ type: "FeatureCollection", features: [] }} regions={{ type: "FeatureCollection", features: [] }} assets={{ type: "FeatureCollection", features: [] }} lens="infrastructureDemand" year={2030} selectedId={null} onSelect={() => undefined} coverage={{ countries: 1, regions: 0, admin1Regions: 0, countriesWithAdmin1: 0, assets: 0, dataCentres: 0, waterInfrastructure: 0 }} generatorOverview={{ type: "FeatureCollection", features: [] }} />,
    );
    expect(mapCalls.sources.find(([id]) => id === "generators")?.[1]).toMatchObject({ cluster: true, clusterRadius: 44, clusterProperties: expect.objectContaining({ solar: expect.any(Array), wind: expect.any(Array) }) });
    expect(mapCalls.layers.find((layer) => layer.id === "generator-overview-markers")).toMatchObject({ maxzoom: 3 });
    expect(mapCalls.layers.find((layer) => layer.id === "generator-clusters")?.paint).toMatchObject({ "circle-color": "#84918E" });
    expect(mapCalls.layers.find((layer) => layer.id === "generator-assets")?.paint).toMatchObject({ "circle-stroke-width": 1.5 });
    expect(mapCalls.layers.find((layer) => layer.id === "water-assets")).toMatchObject({ type: "symbol", layout: { "text-field": "◆" } });
    expect(mapCalls.handlers.some(([event, layer]) => event === "click" && layer === "generator-assets")).toBe(true);
  });

  it("renders global ADM1 before the deeper Europe NUTS-2 layer", () => {
    render(
      <GlobalMap
        countries={{ type: "FeatureCollection", features: [] }}
        admin1={{ type: "FeatureCollection", features: [] }}
        regions={{ type: "FeatureCollection", features: [] }}
        assets={{ type: "FeatureCollection", features: [] }}
        lens="infrastructureDemand" year={2030} selectedId={null} onSelect={() => undefined}
        coverage={{ countries: 246, regions: 334, admin1Regions: 3229, countriesWithAdmin1: 197, assets: 3634, dataCentres: 3533, waterInfrastructure: 101 }}
      />,
    );

    expect(mapCalls.sources.map(([id]) => id)).toContain("admin1");
    const adm1Line = mapCalls.layers.find((layer) => layer.id === "admin1-line");
    const nuts2Line = mapCalls.layers.find((layer) => layer.id === "regions-line");
    expect(adm1Line?.minzoom).toBeUndefined();
    expect(adm1Line?.paint).toMatchObject({
      "line-width": ["interpolate", ["linear"], ["zoom"], 1, 0.35, 3, 0.8, 6, 1.25],
      "line-opacity": ["interpolate", ["linear"], ["zoom"], 1, 0.28, 3, 0.65, 6, 0.9],
    });
    expect(nuts2Line?.minzoom).toBeGreaterThan(3);
    expect(mapCalls.layers.find((layer) => layer.id === "countries-line")?.paint).toMatchObject({ "line-opacity": 0.94, "line-width": ["case", ["==", ["get", "id"], ""], 3.2, 1.6] });
  });

  it("adds collision-aware ADM1 labels and visible selected or hovered outlines", () => {
    render(
      <GlobalMap countries={{ type: "FeatureCollection", features: [] }} admin1={{ type: "FeatureCollection", features: [] }} regions={{ type: "FeatureCollection", features: [] }} assets={{ type: "FeatureCollection", features: [] }} lens="powerBalance" year={2030} selectedId="ADM1-X" onSelect={() => undefined} coverage={{ countries: 246, regions: 334, admin1Regions: 3229, countriesWithAdmin1: 197, assets: 0, dataCentres: 0, waterInfrastructure: 0 }} />,
    );
    const labels = mapCalls.layers.find((layer) => layer.id === "admin1-label");
    expect(labels).toMatchObject({ type: "symbol", source: "admin1", minzoom: 3, layout: { "text-field": ["get", "name"], "text-allow-overlap": false, "text-ignore-placement": false } });
    const outline = mapCalls.layers.find((layer) => layer.id === "admin1-outline");
    expect(JSON.stringify(outline?.paint)).toContain("feature-state");
    expect(JSON.stringify(outline?.paint)).toContain("ADM1-X");
    const ids = mapCalls.layers.map((layer) => layer.id);
    expect(ids.indexOf("admin1-label")).toBeGreaterThan(ids.indexOf("regions-line"));
    expect(ids.indexOf("admin1-label")).toBeLessThan(ids.indexOf("countries-line"));
  });

  it("restores hover feature state after the map is recreated", () => {
    const emptyGeographies: GeographyCollection = { type: "FeatureCollection", features: [] };
    const baseProps = { countries: emptyGeographies, admin1: emptyGeographies, regions: emptyGeographies, lens: "powerBalance" as const, year: 2030, selectedId: null, onSelect: () => undefined, coverage: { countries: 246, regions: 334, admin1Regions: 3229, countriesWithAdmin1: 197, assets: 0, dataCentres: 0, waterInfrastructure: 0 } };
    const firstAssets: AssetCollection = { type: "FeatureCollection", features: [] };
    const { rerender } = render(<GlobalMap {...baseProps} assets={firstAssets} />);
    const firstMove = mapCalls.handlers.find(([event, layer]) => event === "mousemove" && layer === "admin1-fill")?.[2] as ((event: unknown) => void);
    act(() => firstMove({ features: [{ id: "ADM1-X" }] }));
    const secondAssets: AssetCollection = { type: "FeatureCollection", features: [] };
    rerender(<GlobalMap {...baseProps} assets={secondAssets} />);
    const moves = mapCalls.handlers.filter(([event, layer]) => event === "mousemove" && layer === "admin1-fill");
    const secondMove = moves.at(-1)?.[2] as ((event: unknown) => void);
    act(() => secondMove({ features: [{ id: "ADM1-X" }] }));
    expect(mapCalls.featureStates.filter(({ state }) => (state as Record<string, unknown>).hover === true)).toHaveLength(2);
  });

  it("keeps unavailable ADM1 and country-only exceptions selectable without inventing subdivisions", () => {
    const onSelect = vi.fn();
    render(
      <GlobalMap countries={{ type: "FeatureCollection", features: [] }} admin1={{ type: "FeatureCollection", features: [] }} regions={{ type: "FeatureCollection", features: [] }} assets={{ type: "FeatureCollection", features: [] }} lens="powerBalance" year={2030} selectedId={null} onSelect={onSelect} coverage={{ countries: 246, regions: 334, admin1Regions: 3229, countriesWithAdmin1: 197, assets: 0, dataCentres: 0, waterInfrastructure: 0 }} />,
    );
    expect(mapCalls.layers.find((layer) => layer.id === "admin1-fill")?.paint).toMatchObject({ "fill-opacity": ["case", ["==", ["get", "activeScore"], null], 0.04, 0.34] });
    expect(mapCalls.handlers.some(([event, layer]) => event === "click" && layer === "admin1-fill")).toBe(true);
    expect(mapCalls.handlers.some(([event, layer]) => event === "click" && layer === "countries-fill")).toBe(true);
    expect(mapCalls.sources.find(([id]) => id === "admin1")?.[1]).toMatchObject({ data: { features: [] } });
  });
});
