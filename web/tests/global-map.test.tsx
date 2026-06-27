import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("maplibre-gl", () => ({
  default: {
    Map: class {
      addControl() {}
      addSource() {}
      addLayer() {}
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
  it("opens at world scale and reports global coverage", () => {
    render(
      <GlobalMap
        countries={{ type: "FeatureCollection", features: [] }}
        regions={{ type: "FeatureCollection", features: [] }}
        assets={{ type: "FeatureCollection", features: [] }}
        lens="infrastructureDemand"
        year={2030}
        selectedId={null}
        onSelect={() => undefined}
        coverage={{ countries: 246, regions: 334, assets: 14, dataCentres: 8, waterInfrastructure: 6 }}
      />,
    );

    expect(GLOBAL_VIEW.zoom).toBeLessThan(2);
    expect(screen.getByRole("region", { name: "Global opportunity map" })).toBeInTheDocument();
    expect(screen.getByText(/246 countries · 14 infrastructure assets/i)).toBeInTheDocument();
  });
});
