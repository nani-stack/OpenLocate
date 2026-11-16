// The map: start and end pins, the route line, and the simulated position.
// Tiles come from OpenFreeMap (free, no key). MapLibre shows the attribution itself.
// The look is a dark, slate-blue recolouring of OpenFreeMap's dark style (see mapStyle.ts).

import {
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  setWorkerUrl,
  type GeoJSONSource,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre runs its tile work in a web worker and cannot find that file by itself once the
// app is bundled, so the bundler hands us its address.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef, useState } from "react";

import { loadMapStyle } from "../mapStyle";
import type { LatLon, RoutePoint } from "../rpc/types";
import { pathBounds } from "../trip";


setWorkerUrl(workerUrl);

type MapStyle = NonNullable<ConstructorParameters<typeof MapLibreMap>[0]["style"]>;
const ROUTE_SOURCE = "route";

interface Props {
  from: LatLon | null;
  to: LatLon | null;
  path: readonly RoutePoint[] | null;
  position: LatLon | null;
  /** Keep the simulated position in view while it moves. */
  follow: boolean;
  /** Where this computer is, if known. The map opens there. */
  home: LatLon | null;
}

function pin(className: string): HTMLDivElement {
  const element = document.createElement("div");
  element.className = className;
  return element;
}

function routeData(path: readonly RoutePoint[] | null) {
  return {
    type: "Feature" as const,
    properties: {},
    geometry: { type: "LineString" as const, coordinates: (path ?? []).map(([lat, lon]) => [lon, lat]) },
  };
}

export function MapView({ from, to, path, position, follow, home }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markers = useRef<Record<"from" | "to" | "position" | "home", Marker | undefined>>({
    from: undefined,
    to: undefined,
    position: undefined,
    home: undefined,
  });
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    const element = container.current;
    if (element === null) return;
    let cancelled = false;
    let created: MapLibreMap | null = null;
    void loadMapStyle().then((style) => {
      if (cancelled) return;
      try {
        created = start(element, style as MapStyle);
      } catch (error) {
        setFailed(error instanceof Error ? error.message : String(error));
      }
    });
    const held = markers.current;
    return () => {
      cancelled = true;
      held.from = held.to = held.position = held.home = undefined;
      mapRef.current = null;
      setReady(false);
      created?.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function start(
    element: HTMLDivElement,
    style: MapStyle,
  ): MapLibreMap {
    const map = new MapLibreMap({ container: element, style, center: [0, 25], zoom: 1.5 });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      map.addSource(ROUTE_SOURCE, { type: "geojson", data: routeData(null) });
      map.addLayer({
        id: "route-casing",
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#0b1020", "line-width": 9, "line-opacity": 0.9 },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#3b8cff", "line-width": 5 },
      });
      setReady(true);
    });
    mapRef.current = map;
    return map;
  }

  // This computer's own position: a quiet grey dot, and where the map opens.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready || home === null) return;
    markers.current.home?.remove();
    markers.current.home = new Marker({ element: pin("dot dot-home") })
      .setLngLat([home.lon, home.lat])
      .addTo(map);
    if (from === null && to === null && path === null && position === null) {
      map.jumpTo({ center: [home.lon, home.lat], zoom: 14 });
    }
    // Only when the position first arrives: later changes of the trip must not move the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [home, ready]);

  // Start and end pins. With no route yet, bring the newest pin into view.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready) return;
    const place = (key: "from" | "to", point: LatLon | null, className: string) => {
      markers.current[key]?.remove();
      markers.current[key] = undefined;
      if (point !== null) {
        markers.current[key] = new Marker({ element: pin(className), anchor: "bottom" })
          .setLngLat([point.lon, point.lat])
          .addTo(map);
      }
    };
    place("from", from, "pin pin-from");
    place("to", to, "pin pin-to");
    if (path !== null) return;
    if (from !== null && to !== null) {
      const bounds = new LngLatBounds([from.lon, from.lat], [from.lon, from.lat]);
      bounds.extend([to.lon, to.lat]);
      map.fitBounds(bounds, { padding: 80, maxZoom: 15, duration: 600 });
    } else {
      const only = from ?? to;
      if (only !== null) map.flyTo({ center: [only.lon, only.lat], zoom: 14, duration: 600 });
    }
  }, [from, to, path, ready]);

  // The route line, and the view that shows all of it.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready) return;
    (map.getSource(ROUTE_SOURCE) as GeoJSONSource | undefined)?.setData(routeData(path));
    const box = path === null ? null : pathBounds(path);
    if (box !== null) {
      map.fitBounds(
        [
          [box[0], box[1]],
          [box[2], box[3]],
        ],
        { padding: 60, maxZoom: 16, duration: 600 },
      );
    }
  }, [path, ready]);

  // The simulated position.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready) return;
    if (position === null) {
      markers.current.position?.remove();
      markers.current.position = undefined;
      return;
    }
    const lngLat: [number, number] = [position.lon, position.lat];
    if (markers.current.position === undefined) {
      markers.current.position = new Marker({ element: pin("dot") }).setLngLat(lngLat).addTo(map);
    } else {
      markers.current.position.setLngLat(lngLat);
    }
    if (follow && !map.getBounds().contains(lngLat)) {
      map.easeTo({ center: lngLat, duration: 500 });
    }
  }, [position, follow, ready]);

  return (
    <div className="map-wrap">
      <div ref={container} className="map" />
      {failed && (
        <p className="map-failed">
          The map could not start ({failed}). Search, routes and playback still work.
        </p>
      )}
    </div>
  );
}
