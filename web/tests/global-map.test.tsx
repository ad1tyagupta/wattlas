import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mapCalls = vi.hoisted(() => ({
  sources: [] as Array<[string, Record<string, unknown>]>,
  layers: [] as Array<Record<string, unknown>>,
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
      on(event: string, layerOrHandler: unknown) {
        if (event === "load" && typeof layerOrHandler === "function") layerOrHandler();
      }
      remove() {}
      setPaintProperty() {}
    },
    NavigationControl: class {},
    AttributionControl: class {},
  },
}));

import { GLOBAL_VIEW, GlobalMap } from "@/components/map/global-map";

describe("GlobalMap", () => {
  beforeEach(() => {
    mapCalls.sources.length = 0;
    mapCalls.layers.length = 0;
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
    expect(adm1Line?.minzoom).toBeLessThan(nuts2Line?.minzoom as number);
    expect(mapCalls.layers.find((layer) => layer.id === "countries-line")?.paint).toMatchObject({ "line-opacity": 0.94 });
  });
});
