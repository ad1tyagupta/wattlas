"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import { useEffect, useMemo, useRef } from "react";
import maplibregl, { type GeoJSONSource, type MapGeoJSONFeature, type MapMouseEvent } from "maplibre-gl";

import { baseMapStyle } from "@/components/map/map-style";
import { assetColor, assetStrokeColorExpression, countryBorderWidthExpression, mapColorExpression } from "@/lib/map/expressions";
import type {
  AssetCollection,
  GeographyCollection,
  LensKey,
  SnapshotManifest,
} from "@/lib/snapshot/types";

type Props = {
  countries: GeographyCollection;
  admin1: GeographyCollection;
  regions: GeographyCollection;
  assets: AssetCollection;
  lens: LensKey;
  year: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  coverage: SnapshotManifest["coverage"];
};

export const GLOBAL_VIEW = { center: [12, 22] as [number, number], zoom: 1.25 };

function activeCountries(countries: GeographyCollection, lens: LensKey, year: number): GeoJSON.FeatureCollection {
  return {
    ...countries,
    features: countries.features.map((feature) => ({
      ...feature,
      properties: {
        ...feature.properties,
        activeScore:
          feature.properties.categoryScoresByYear[String(year)]?.combined?.[lens]
          ?? feature.properties.scoresByYear[String(year)]?.[lens]
          ?? null,
      },
    })),
  };
}

function activeRegions(regions: GeographyCollection, lens: LensKey, year: number): GeoJSON.FeatureCollection {
  return {
    ...regions,
    features: regions.features.map((feature) => ({
      ...feature,
      properties: {
        ...feature.properties,
        activeScore: feature.properties.scoresByYear[String(year)]?.[lens] ?? null,
      },
    })),
  };
}

export function GlobalMap({ countries, admin1, regions, assets, lens, year, selectedId, onSelect, coverage }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const onSelectRef = useRef(onSelect);
  const preparedCountries = useMemo(() => activeCountries(countries, lens, year), [countries, lens, year]);
  const preparedAdmin1 = useMemo(() => activeCountries(admin1, lens, year), [admin1, lens, year]);
  const preparedRegions = useMemo(() => activeRegions(regions, lens, year), [regions, lens, year]);
  const countriesRef = useRef(preparedCountries);
  const admin1Ref = useRef(preparedAdmin1);
  const regionsRef = useRef(preparedRegions);
  const selectedIdRef = useRef(selectedId);
  const lensRef = useRef(lens);

  useEffect(() => {
    onSelectRef.current = onSelect;
    countriesRef.current = preparedCountries;
    admin1Ref.current = preparedAdmin1;
    regionsRef.current = preparedRegions;
    selectedIdRef.current = selectedId;
    lensRef.current = lens;
  }, [lens, onSelect, preparedAdmin1, preparedCountries, preparedRegions, selectedId]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const container = containerRef.current;
    const map = new maplibregl.Map({
      container,
      style: baseMapStyle,
      center: GLOBAL_VIEW.center,
      zoom: GLOBAL_VIEW.zoom,
      minZoom: 0.8,
      maxZoom: 8,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-left");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      map.addSource("countries", { type: "geojson", data: countriesRef.current, promoteId: "id" });
      map.addSource("admin1", { type: "geojson", data: admin1Ref.current, promoteId: "id" });
      map.addSource("regions", { type: "geojson", data: regionsRef.current, promoteId: "id" });
      map.addSource("assets", {
        type: "geojson",
        data: assets,
        cluster: true,
        clusterRadius: 48,
        clusterMaxZoom: 6,
      });
      map.addLayer({
        id: "countries-fill",
        type: "fill",
        source: "countries",
        paint: {
          "fill-color": mapColorExpression(lensRef.current),
          "fill-opacity": ["case", ["==", ["get", "activeScore"], null], 0.5, 0.86],
        },
      });
      map.addLayer({
        id: "admin1-fill",
        type: "fill",
        source: "admin1",
        minzoom: 2.2,
        paint: {
          "fill-color": mapColorExpression(lensRef.current),
          "fill-opacity": ["case", ["==", ["get", "activeScore"], null], 0.04, 0.34],
        },
      });
      map.addLayer({
        id: "admin1-line",
        type: "line",
        source: "admin1",
        minzoom: 2.2,
        paint: {
          "line-color": ["case", ["==", ["get", "id"], selectedIdRef.current ?? ""], "#E1EBE8", "#38514C"],
          "line-width": ["case", ["==", ["get", "id"], selectedIdRef.current ?? ""], 2.1, 0.55],
          "line-opacity": 0.72,
        },
      });
      map.addLayer({
        id: "regions-fill",
        type: "fill",
        source: "regions",
        minzoom: 4.5,
        paint: {
          "fill-color": mapColorExpression(lensRef.current),
          "fill-opacity": ["case", ["==", ["get", "activeScore"], null], 0.1, 0.58],
        },
      });
      map.addLayer({
        id: "regions-line",
        type: "line",
        source: "regions",
        minzoom: 4.5,
        paint: {
          "line-color": ["case", ["==", ["get", "id"], selectedIdRef.current ?? ""], "#E1EBE8", "#47635E"],
          "line-width": ["case", ["==", ["get", "id"], selectedIdRef.current ?? ""], 2.2, 0.5],
          "line-opacity": 0.72,
        },
      });
      map.addLayer({
        id: "countries-line",
        type: "line",
        source: "countries",
        paint: {
          "line-color": ["case", ["==", ["get", "id"], selectedIdRef.current ?? ""], "#F1F6F4", "#76908A"],
          "line-width": countryBorderWidthExpression(selectedIdRef.current),
          "line-opacity": 0.94,
        },
      });
      map.addLayer({
        id: "asset-clusters",
        type: "circle",
        source: "assets",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#E2B45C",
          "circle-radius": ["step", ["get", "point_count"], 14, 25, 18, 100, 23, 500, 29],
          "circle-opacity": 0.9,
          "circle-stroke-color": "#07100F",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "asset-cluster-count",
        type: "symbol",
        source: "assets",
        filter: ["has", "point_count"],
        layout: {
          "text-field": ["get", "point_count_abbreviated"],
          "text-size": 11,
        },
        paint: { "text-color": "#07100F" },
      });
      map.addLayer({
        id: "data-centre-assets",
        type: "circle",
        source: "assets",
        filter: ["all", ["!", ["has", "point_count"]], ["==", ["get", "category"], "data_centre"]],
        paint: {
          "circle-color": assetColor("data_centre"),
          "circle-radius": 6,
          "circle-opacity": ["case", ["==", ["get", "lifecycle"], "operational"], 0.68, 1],
          "circle-stroke-color": assetStrokeColorExpression(),
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "water-assets",
        type: "circle",
        source: "assets",
        filter: ["all", ["!", ["has", "point_count"]], ["==", ["get", "category"], "water_infrastructure"]],
        paint: {
          "circle-color": assetColor("water_infrastructure"),
          "circle-radius": 5,
          "circle-opacity": ["case", ["==", ["get", "lifecycle"], "operational"], 0.68, 1],
          "circle-stroke-color": assetStrokeColorExpression(),
          "circle-stroke-width": 1.25,
        },
      });

      for (const layer of ["countries-fill", "admin1-fill", "regions-fill", "asset-clusters", "data-centre-assets", "water-assets"]) {
        map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
      }
      const selectGeography = (event: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
        const properties = event.features?.[0]?.properties;
        const id = properties?.id;
        if (!id) return;
        onSelectRef.current(id);
      };
      const selectAsset = (event: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
        const id = event.features?.[0]?.properties?.id;
        if (id) onSelectRef.current(id);
      };
      map.on("click", "asset-clusters", async (event) => {
        const feature = event.features?.[0];
        const clusterId = Number(feature?.properties?.cluster_id);
        const coordinates = feature?.geometry.type === "Point" ? feature.geometry.coordinates : null;
        const source = map.getSource("assets") as GeoJSONSource | undefined;
        if (!source || !coordinates || !Number.isFinite(clusterId)) return;
        const zoom = await source.getClusterExpansionZoom(clusterId);
        map.easeTo({ center: [coordinates[0], coordinates[1]], zoom });
      });
      map.on("click", "countries-fill", selectGeography);
      map.on("click", "admin1-fill", selectGeography);
      map.on("click", "regions-fill", selectGeography);
      map.on("click", "data-centre-assets", selectAsset);
      map.on("click", "water-assets", selectAsset);
      container.setAttribute("data-map-loaded", "true");
    });
    return () => {
      container.removeAttribute("data-map-loaded");
      map.remove();
      mapRef.current = null;
    };
  }, [assets]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    (map.getSource("countries") as GeoJSONSource | undefined)?.setData(preparedCountries);
    (map.getSource("admin1") as GeoJSONSource | undefined)?.setData(preparedAdmin1);
    (map.getSource("regions") as GeoJSONSource | undefined)?.setData(preparedRegions);
    if (map.getLayer("countries-fill")) map.setPaintProperty("countries-fill", "fill-color", mapColorExpression(lens));
    if (map.getLayer("admin1-fill")) map.setPaintProperty("admin1-fill", "fill-color", mapColorExpression(lens));
    if (map.getLayer("regions-fill")) map.setPaintProperty("regions-fill", "fill-color", mapColorExpression(lens));
  }, [lens, preparedAdmin1, preparedCountries, preparedRegions]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    if (map.getLayer("countries-line")) {
      map.setPaintProperty("countries-line", "line-width", countryBorderWidthExpression(selectedId));
      map.setPaintProperty("countries-line", "line-color", ["case", ["==", ["get", "id"], selectedId ?? ""], "#F1F6F4", "#76908A"]);
    }
    if (map.getLayer("regions-line")) {
      map.setPaintProperty("regions-line", "line-width", ["case", ["==", ["get", "id"], selectedId ?? ""], 2.2, 0.5]);
    }
    if (map.getLayer("admin1-line")) {
      map.setPaintProperty("admin1-line", "line-width", ["case", ["==", ["get", "id"], selectedId ?? ""], 2.1, 0.55]);
    }
  }, [selectedId]);

  const label = lens === "infrastructureDemand"
    ? "Infrastructure Demand"
    : lens === "siteAttractiveness"
      ? "Site Attractiveness"
      : lens === "systemRisk"
        ? "System Risk"
        : "Power Balance";
  return (
    <section className="map-panel" aria-label="Global opportunity map" data-admin1-count={admin1.features.length}>
      <div className="map-meta">
        <span>{year}</span>
        <strong>{label}</strong>
        <small>{coverage.countries} countries · {coverage.assets} infrastructure assets</small>
      </div>
      <div ref={containerRef} className="map-container" data-testid="global-map" />
      <div className="data-attribution">
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" aria-label="OpenStreetMap infrastructure attribution">Infrastructure © OpenStreetMap contributors · ODbL</a>
        <span> · </span><a href="https://www.geoboundaries.org/" target="_blank" rel="noreferrer">Regions © geoBoundaries · CC BY 4.0</a>
        <span> · India boundary perspective: Government of India</span>
      </div>
    </section>
  );
}
