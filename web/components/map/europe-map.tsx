"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import { useEffect, useMemo, useRef } from "react";
import maplibregl, { type GeoJSONSource, type MapGeoJSONFeature, type MapMouseEvent } from "maplibre-gl";

import { baseMapStyle } from "@/components/map/map-style";
import { mapColorExpression } from "@/lib/map/expressions";
import type { LensKey, ProjectCollection, RegionCollection } from "@/lib/snapshot/types";

type Props = {
  regions: RegionCollection;
  projects: ProjectCollection;
  lens: LensKey;
  year: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
};

function activeRegions(regions: RegionCollection, lens: LensKey, year: number): GeoJSON.FeatureCollection {
  return {
    ...regions,
    features: regions.features.map((feature) => ({
      ...feature,
      properties: { ...feature.properties, activeScore: feature.properties.scoresByYear[String(year)]?.[lens] ?? null },
    })),
  };
}

export function EuropeMap({ regions, projects, lens, year, selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const onSelectRef = useRef(onSelect);
  const prepared = useMemo(() => activeRegions(regions, lens, year), [regions, lens, year]);
  const preparedRef = useRef(prepared);
  const lensRef = useRef(lens);
  const selectedIdRef = useRef(selectedId);

  useEffect(() => {
    onSelectRef.current = onSelect;
    preparedRef.current = prepared;
    lensRef.current = lens;
    selectedIdRef.current = selectedId;
  }, [lens, onSelect, prepared, selectedId]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const container = containerRef.current;
    const map = new maplibregl.Map({
      container,
      style: baseMapStyle,
      center: [9.5, 50.5],
      zoom: 3.25,
      minZoom: 2.2,
      maxZoom: 8,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-left");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      map.addSource("regions", { type: "geojson", data: preparedRef.current, promoteId: "id" });
      map.addSource("projects", { type: "geojson", data: projects, cluster: true, clusterRadius: 32 });
      map.addLayer({
        id: "regions-fill", type: "fill", source: "regions",
        paint: {
          "fill-color": mapColorExpression(lensRef.current),
          "fill-opacity": ["case", ["==", ["get", "activeScore"], null], 0.52, 0.84],
        },
      });
      map.addLayer({
        id: "regions-line", type: "line", source: "regions",
        paint: {
          "line-color": ["case", ["==", ["get", "id"], selectedIdRef.current ?? ""], "#E1EBE8", "#47635E"],
          "line-width": ["case", ["==", ["get", "id"], selectedIdRef.current ?? ""], 2.4, 0.65],
          "line-opacity": 0.9,
        },
      });
      map.addLayer({
        id: "project-clusters", type: "circle", source: "projects", filter: ["has", "point_count"],
        paint: { "circle-color": "#07100F", "circle-stroke-color": "#72D9BD", "circle-stroke-width": 1.5, "circle-radius": 14 },
      });
      map.addLayer({
        id: "project-points", type: "circle", source: "projects", filter: ["!", ["has", "point_count"]],
        paint: { "circle-color": "#E1EBE8", "circle-stroke-color": "#07100F", "circle-stroke-width": 2, "circle-radius": 5 },
      });
      map.on("mouseenter", "regions-fill", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "regions-fill", () => { map.getCanvas().style.cursor = ""; });
      map.on("click", "regions-fill", (event: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
        const id = event.features?.[0]?.properties?.id as string | undefined;
        if (!id) return;
        onSelectRef.current(id);
        map.easeTo({ center: event.lngLat, zoom: Math.max(map.getZoom(), 4.25), duration: 650 });
      });
      container.setAttribute("data-map-loaded", "true");
    });
    return () => { container.removeAttribute("data-map-loaded"); map.remove(); mapRef.current = null; };
  }, [projects, regions]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    (map.getSource("regions") as GeoJSONSource | undefined)?.setData(prepared);
    if (map.getLayer("regions-fill")) map.setPaintProperty("regions-fill", "fill-color", mapColorExpression(lens));
  }, [prepared, lens]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded() || !map.getLayer("regions-line")) return;
    map.setPaintProperty("regions-line", "line-color", ["case", ["==", ["get", "id"], selectedId ?? ""], "#E1EBE8", "#47635E"]);
    map.setPaintProperty("regions-line", "line-width", ["case", ["==", ["get", "id"], selectedId ?? ""], 2.4, 0.65]);
  }, [selectedId]);

  const label = lens === "infrastructureDemand" ? "Infrastructure Demand" : lens === "siteAttractiveness" ? "Site Attractiveness" : "System Risk";
  return (
    <section className="map-panel" aria-label="European opportunity map">
      <div className="map-meta"><span>{year}</span><strong>{label}</strong><small>334 NUTS 2 regions · 8 evidence-rich clusters</small></div>
      <div
        ref={containerRef}
        className="map-container"
        data-testid="europe-map"
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      />
    </section>
  );
}
