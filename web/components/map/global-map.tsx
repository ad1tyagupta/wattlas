"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import { useEffect, useMemo, useRef } from "react";
import maplibregl, { type ExpressionSpecification, type GeoJSONSource, type MapGeoJSONFeature, type MapMouseEvent } from "maplibre-gl";

import { baseMapStyle } from "@/components/map/map-style";
import type { InfrastructureVisibility } from "@/components/controls/layer-rail";
import { generatorColorExpression, generatorTechnologyExpression } from "@/lib/map/generator-colors";
import { countriesInBounds, createGeneratorShardController, filterGeneratorOverview, filterGenerators, generatorSelection, type MapBounds } from "@/lib/map/generator-shards";
import { admin1LineOpacityExpression, admin1LineWidthExpression, assetColor, assetStrokeColorExpression, countryBorderWidthExpression, mapColorExpression } from "@/lib/map/expressions";
import type {
  AssetCollection,
  GeographyCollection,
  LensKey,
  SnapshotManifest,
  GenerationTechnology,
  GeneratorFeature,
  GeneratorIndex,
  GeneratorOverviewCollection,
  GeneratorCollection,
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
  infrastructure?: InfrastructureVisibility;
  technologies?: ReadonlySet<GenerationTechnology>;
  lifecycles?: ReadonlySet<string>;
  generatorOverview?: GeneratorOverviewCollection | null;
  generatorIndex?: GeneratorIndex | null;
  snapshotRoot?: string | null;
  onSelectGenerator?: (generator: GeneratorFeature) => void;
  onVisibleGeneratorsChange?: (ids: ReadonlySet<string>) => void;
};

export const GLOBAL_VIEW = { center: [12, 22] as [number, number], zoom: 1.25 };

function visibleAssets(assets: AssetCollection, infrastructure: InfrastructureVisibility): AssetCollection {
  return { ...assets, features: assets.features.filter(({ properties }) => properties.category === "data_centre" ? infrastructure.dataCentres : infrastructure.water) };
}

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

const EMPTY_GENERATORS: GeneratorCollection = { type: "FeatureCollection", features: [] };
const EMPTY_OVERVIEW: GeneratorOverviewCollection = { type: "FeatureCollection", features: [] };

export function GlobalMap({ countries, admin1, regions, assets, lens, year, selectedId, onSelect, coverage, infrastructure = { dataCentres: true, water: true, generators: true }, technologies = new Set<GenerationTechnology>(["solar", "wind", "hydro", "nuclear", "gas", "coal", "oil", "biomass", "geothermal", "other"]), lifecycles = new Set(["operational", "under_construction", "announced", "planning_filed", "permitted", "paused", "cancelled", "retired", "decommissioned", "shelved", "unknown"]), generatorOverview = null, generatorIndex = null, snapshotRoot = null, onSelectGenerator, onVisibleGeneratorsChange }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const onSelectRef = useRef(onSelect);
  const onSelectGeneratorRef = useRef(onSelectGenerator);
  const onVisibleGeneratorsChangeRef = useRef(onVisibleGeneratorsChange);
  const infrastructureRef = useRef(infrastructure);
  const generatorControllerRef = useRef<ReturnType<typeof createGeneratorShardController> | null>(null);
  const activeGeneratorsRef = useRef<GeneratorCollection>(EMPTY_GENERATORS);
  const generatorFiltersRef = useRef({ technologies, lifecycles });
  const preparedCountries = useMemo(() => activeCountries(countries, lens, year), [countries, lens, year]);
  const preparedAdmin1 = useMemo(() => activeCountries(admin1, lens, year), [admin1, lens, year]);
  const preparedRegions = useMemo(() => activeRegions(regions, lens, year), [regions, lens, year]);
  const preparedGeneratorOverview = useMemo(() => filterGeneratorOverview(generatorOverview ?? EMPTY_OVERVIEW, technologies, lifecycles), [generatorOverview, lifecycles, technologies]);
  const generatorOverviewRef = useRef(preparedGeneratorOverview);
  const countriesRef = useRef(preparedCountries);
  const admin1Ref = useRef(preparedAdmin1);
  const regionsRef = useRef(preparedRegions);
  const selectedIdRef = useRef(selectedId);
  const lensRef = useRef(lens);
  const hoveredAdmin1Ref = useRef<string | number | null>(null);

  useEffect(() => {
    onSelectRef.current = onSelect;
    onSelectGeneratorRef.current = onSelectGenerator;
    onVisibleGeneratorsChangeRef.current = onVisibleGeneratorsChange;
    countriesRef.current = preparedCountries;
    admin1Ref.current = preparedAdmin1;
    regionsRef.current = preparedRegions;
    selectedIdRef.current = selectedId;
    lensRef.current = lens;
    generatorFiltersRef.current = { technologies, lifecycles };
    infrastructureRef.current = infrastructure;
    generatorOverviewRef.current = preparedGeneratorOverview;
  }, [infrastructure, lens, lifecycles, onSelect, onSelectGenerator, onVisibleGeneratorsChange, preparedAdmin1, preparedCountries, preparedGeneratorOverview, preparedRegions, selectedId, technologies]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const container = containerRef.current;
    const map = new maplibregl.Map({
      container,
      style: baseMapStyle,
      center: GLOBAL_VIEW.center,
      zoom: GLOBAL_VIEW.zoom,
      minZoom: 0.8,
      maxZoom: 12,
      attributionControl: false,
    });
    hoveredAdmin1Ref.current = null;
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-left");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      map.addSource("countries", { type: "geojson", data: countriesRef.current, promoteId: "id" });
      map.addSource("admin1", { type: "geojson", data: admin1Ref.current, promoteId: "id" });
      map.addSource("regions", { type: "geojson", data: regionsRef.current, promoteId: "id" });
      map.addSource("assets", {
        type: "geojson",
        data: visibleAssets(assets, infrastructureRef.current),
        cluster: true,
        clusterRadius: 48,
        clusterMaxZoom: 6,
      });
      map.addSource("generator-overview", { type: "geojson", data: generatorOverviewRef.current ?? EMPTY_OVERVIEW });
      map.addSource("generators", {
        type: "geojson", data: EMPTY_GENERATORS, cluster: true, clusterRadius: 44, clusterMaxZoom: 8,
        clusterProperties: {
          solar: ["+", ["case", ["in", "solar", ["get", "technologies"]], 1, 0]],
          wind: ["+", ["case", ["in", "wind", ["get", "technologies"]], 1, 0]],
          hydro: ["+", ["case", ["in", "hydro", ["get", "technologies"]], 1, 0]],
          nuclear: ["+", ["case", ["in", "nuclear", ["get", "technologies"]], 1, 0]],
          gas: ["+", ["case", ["in", "gas", ["get", "technologies"]], 1, 0]],
          coal: ["+", ["case", ["in", "coal", ["get", "technologies"]], 1, 0]],
          oil: ["+", ["case", ["in", "oil", ["get", "technologies"]], 1, 0]],
          biomass: ["+", ["case", ["in", "biomass", ["get", "technologies"]], 1, 0]],
          geothermal: ["+", ["case", ["in", "geothermal", ["get", "technologies"]], 1, 0]],
          other: ["+", ["case", ["in", "other", ["get", "technologies"]], 1, 0]],
        },
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
        paint: {
          "line-color": "#49635E",
          "line-width": admin1LineWidthExpression(),
          "line-opacity": admin1LineOpacityExpression(),
        },
      });
      map.addLayer({
        id: "admin1-outline",
        type: "line",
        source: "admin1",
        paint: {
          "line-color": "#F1F6F4",
          "line-width": ["case", ["any", ["==", ["get", "id"], selectedIdRef.current ?? ""], ["boolean", ["feature-state", "hover"], false]], 2.6, 0],
          "line-opacity": 0.96,
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
        id: "admin1-label",
        type: "symbol",
        source: "admin1",
        minzoom: 3,
        layout: {
          "text-field": ["get", "name"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 3, 10, 6, 12],
          "text-allow-overlap": false,
          "text-ignore-placement": false,
          "text-optional": true,
        },
        paint: {
          "text-color": "#D7E2DF",
          "text-halo-color": "#0B1715",
          "text-halo-width": 1.25,
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
      map.addLayer({ id: "generator-overview-markers", type: "circle", source: "generator-overview", maxzoom: 3, layout: { visibility: infrastructureRef.current.generators ? "visible" : "none" }, paint: { "circle-color": ["case", ["boolean", ["get", "isMixed"], false], "#84918E", generatorColorExpression("displayTechnology")], "circle-radius": ["step", ["get", "count"], 5, 10, 8, 50, 11], "circle-stroke-color": "#07100F", "circle-stroke-width": 1.5, "circle-opacity": 0.9 } });
      map.addLayer({ id: "generator-overview-composition", type: "symbol", source: "generator-overview", minzoom: 1.8, maxzoom: 3, layout: { visibility: infrastructureRef.current.generators ? "visible" : "none", "text-field": ["get", "overviewLabel"], "text-size": 9, "text-offset": [0, 1.4], "text-optional": true }, paint: { "text-color": "#D7E2DF", "text-halo-color": "#07100F", "text-halo-width": 1 } });
      const technologyKindCount = ["+", ...(["solar", "wind", "hydro", "nuclear", "gas", "coal", "oil", "biomass", "geothermal", "other"].map((technology) => ["case", [">", ["get", technology], 0], 1, 0]))] as unknown as ExpressionSpecification;
      map.addLayer({ id: "generator-clusters", type: "circle", source: "generators", minzoom: 3, filter: ["has", "point_count"], paint: { "circle-color": ["case", [">", technologyKindCount, 1], "#84918E", ["case", [">", ["get", "solar"], 0], "#E7B84B", [">", ["get", "wind"], 0], "#55C7D9", [">", ["get", "hydro"], 0], "#4E8EDB", [">", ["get", "nuclear"], 0], "#A98AE8", [">", ["get", "gas"], 0], "#E07A5F", [">", ["get", "coal"], 0], "#6F7782", [">", ["get", "oil"], 0], "#B88762", [">", ["get", "biomass"], 0], "#78B77A", [">", ["get", "geothermal"], 0], "#D98255", "#9AA6A4"]], "circle-radius": ["step", ["get", "point_count"], 13, 25, 18, 100, 24], "circle-stroke-color": "#E8EFED", "circle-stroke-width": 1.5 } });
      map.addLayer({ id: "generator-cluster-count", type: "symbol", source: "generators", minzoom: 3, filter: ["has", "point_count"], layout: { "text-field": ["concat", ["get", "point_count_abbreviated"], " · composition S", ["get", "solar"], " W", ["get", "wind"], " H", ["get", "hydro"], " N", ["get", "nuclear"], " G", ["get", "gas"], " C", ["get", "coal"], " O", ["get", "oil"], " B", ["get", "biomass"], " T", ["get", "geothermal"], " X", ["get", "other"]], "text-size": 9, "text-offset": [0, 2] }, paint: { "text-color": "#D7E2DF", "text-halo-color": "#07100F", "text-halo-width": 1 } });
      map.addLayer({ id: "generator-assets", type: "symbol", source: "generators", minzoom: 3, filter: ["!", ["has", "point_count"]], layout: { "text-field": "■", "text-size": 13, "text-allow-overlap": true }, paint: { "text-color": generatorTechnologyExpression(), "text-halo-color": "#F1F6F4", "text-halo-width": 1, "text-opacity": ["case", ["==", ["get", "lifecycle"], "operational"], 0.82, 1] } });
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
        type: "symbol",
        source: "assets",
        filter: ["all", ["!", ["has", "point_count"]], ["==", ["get", "category"], "water_infrastructure"]],
        layout: { "text-field": "◆", "text-size": 14, "text-allow-overlap": true },
        paint: {
          "text-color": assetColor("water_infrastructure"),
          "text-halo-color": "#07100F",
          "text-halo-width": 1.5,
          "text-opacity": ["case", ["==", ["get", "lifecycle"], "operational"], 0.72, 1],
        },
      });

      for (const layer of ["countries-fill", "admin1-fill", "regions-fill", "asset-clusters", "data-centre-assets", "water-assets", "generator-overview-markers", "generator-clusters", "generator-assets"]) {
        map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
      }
      map.on("mousemove", "admin1-fill", (event) => {
        const id = event.features?.[0]?.id;
        if (id === hoveredAdmin1Ref.current) return;
        if (hoveredAdmin1Ref.current !== null) map.setFeatureState({ source: "admin1", id: hoveredAdmin1Ref.current }, { hover: false });
        hoveredAdmin1Ref.current = id ?? null;
        if (id !== undefined) map.setFeatureState({ source: "admin1", id }, { hover: true });
      });
      map.on("mouseleave", "admin1-fill", () => {
        if (hoveredAdmin1Ref.current !== null) map.setFeatureState({ source: "admin1", id: hoveredAdmin1Ref.current }, { hover: false });
        hoveredAdmin1Ref.current = null;
      });
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
      map.on("click", "generator-assets", (event) => {
        const id = event.features?.[0]?.properties?.id;
        const generator = generatorSelection(activeGeneratorsRef.current, id);
        if (generator) onSelectGeneratorRef.current?.(generator);
      });
      map.on("click", "generator-clusters", async (event) => {
        const feature = event.features?.[0];
        const clusterId = Number(feature?.properties?.cluster_id);
        const coordinates = feature?.geometry.type === "Point" ? feature.geometry.coordinates : null;
        const source = map.getSource("generators") as GeoJSONSource | undefined;
        if (!source || !coordinates || !Number.isFinite(clusterId)) return;
        map.easeTo({ center: [coordinates[0], coordinates[1]], zoom: await source.getClusterExpansionZoom(clusterId) });
      });
      container.setAttribute("data-map-loaded", "true");
    });
    return () => {
      hoveredAdmin1Ref.current = null;
      container.removeAttribute("data-map-loaded");
      map.remove();
      mapRef.current = null;
    };
  }, [assets]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    (map.getSource("generator-overview") as GeoJSONSource | undefined)?.setData(preparedGeneratorOverview);
  }, [preparedGeneratorOverview]);

  useEffect(() => {
    const map = mapRef.current;
    generatorControllerRef.current?.dispose();
    generatorControllerRef.current = null;
    activeGeneratorsRef.current = EMPTY_GENERATORS;
    if (!map || !generatorIndex || !snapshotRoot) return;
    const controller = createGeneratorShardController(snapshotRoot, generatorIndex);
    generatorControllerRef.current = controller;
    const refresh = async () => {
      if (map.getZoom() < 3 || !infrastructure.generators) {
        activeGeneratorsRef.current = EMPTY_GENERATORS;
        (map.getSource("generators") as GeoJSONSource | undefined)?.setData(EMPTY_GENERATORS);
        onVisibleGeneratorsChangeRef.current?.(new Set());
        return;
      }
      const bounds = map.getBounds();
      const visible = countriesInBounds(generatorIndex, [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()] as MapBounds);
      const combined = await controller.show(visible);
      if (generatorControllerRef.current !== controller) return;
      activeGeneratorsRef.current = combined;
      const filters = generatorFiltersRef.current;
      const filtered = filterGenerators(combined, filters.technologies, filters.lifecycles);
      (map.getSource("generators") as GeoJSONSource | undefined)?.setData(filtered);
      onVisibleGeneratorsChangeRef.current?.(new Set(filtered.features.map((feature) => feature.properties.id)));
    };
    map.on("moveend", refresh);
    void refresh();
    return () => {
      map.off("moveend", refresh);
      controller.dispose();
      if (generatorControllerRef.current === controller) generatorControllerRef.current = null;
    };
  }, [generatorIndex, infrastructure.generators, snapshotRoot]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const filtered = filterGenerators(activeGeneratorsRef.current, technologies, lifecycles);
    (map.getSource("generators") as GeoJSONSource | undefined)?.setData(filtered);
    onVisibleGeneratorsChangeRef.current?.(new Set(filtered.features.map((feature) => feature.properties.id)));
    (map.getSource("assets") as GeoJSONSource | undefined)?.setData(visibleAssets(assets, infrastructure));
    for (const id of ["data-centre-assets"]) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", infrastructure.dataCentres ? "visible" : "none");
    for (const id of ["water-assets"]) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", infrastructure.water ? "visible" : "none");
    for (const id of ["generator-overview-markers", "generator-overview-composition", "generator-clusters", "generator-cluster-count", "generator-assets"]) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", infrastructure.generators ? "visible" : "none");
  }, [assets, infrastructure, lifecycles, technologies]);

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
    if (map.getLayer("admin1-outline")) {
      map.setPaintProperty("admin1-outline", "line-width", ["case", ["any", ["==", ["get", "id"], selectedId ?? ""], ["boolean", ["feature-state", "hover"], false]], 2.6, 0]);
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
      <div className="map-composition-key" aria-label="Generator cluster composition">Cluster labels show technology counts; mixed clusters are neutral. At world scale lifecycle filters exclude aggregates only when no selected plants match; partial lifecycle matches retain unfiltered capacity and technology mix and are labelled approximate.</div>
      <div className="data-attribution" aria-label="Map data and project attribution">
        <span>
          Boundaries: <a href="https://www.un.org/geospatial/mapsgeo" target="_blank" rel="noreferrer">United Nations</a>
          {" · "}<a href="https://ec.europa.eu/eurostat/web/gisco" target="_blank" rel="noreferrer">GISCO</a>
          {" · "}<a href="https://www.geoboundaries.org/" target="_blank" rel="noreferrer">geoBoundaries</a>
          {" · "}<a href="https://surveyofindia.gov.in/" target="_blank" rel="noreferrer">India boundary perspective: Government of India</a>
          {" · "}<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" aria-label="OpenStreetMap infrastructure attribution">Infrastructure © OpenStreetMap contributors · ODbL</a>
        </span>
        <a className="creator-attribution" href="https://github.com/ad1tyagupta/wattlas" target="_blank" rel="noreferrer" aria-label="Wattlas open-source project by Aditya Gupta">
          Created by Aditya Gupta · Open-source project
        </a>
      </div>
    </section>
  );
}
