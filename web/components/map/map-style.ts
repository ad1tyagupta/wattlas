import type { StyleSpecification } from "maplibre-gl";

export const baseMapStyle: StyleSpecification = {
  version: 8,
  name: "GRID//SCOPE mineral cartography",
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#07100F" } }],
};
