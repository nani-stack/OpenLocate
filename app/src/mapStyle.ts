// The map's look: OpenFreeMap's "dark" style, recoloured towards the slate-blue night look of
// phone map apps (blue-grey land, navy water, dark green parks, pale labels). The style is
// fetched once and its colours are replaced here, so nothing but OpenFreeMap is contacted.

export const BASE_STYLE_URL = "https://tiles.openfreemap.org/styles/dark";

const LAND = "#2a2f3b";
const WATER = "#17264d";
const PARK = "#1e4032";
const BUILDING = "#353c4c";
const ROAD_SMALL = "#454d5f";
const ROAD_BIG = "#5d6679";
const ROAD_EDGE = "#20242d";
const RAIL = "#3a4151";
const LABEL = "#d6dbe6";
const LABEL_DIM = "#9aa3b5";
const HALO = "rgba(24, 27, 35, 0.85)";

type Paint = Record<string, unknown>;

/** Colours for one layer, chosen from its id. Null leaves the layer as it is. */
export function paintFor(id: string, type: string): Paint | null {
  if (type === "background") return { "background-color": LAND };
  if (type === "symbol") {
    if (id.startsWith("water")) return { "text-color": "#7f97d1", "text-halo-color": WATER };
    if (id.startsWith("highway_name")) return { "text-color": LABEL_DIM, "text-halo-color": HALO };
    if (id.startsWith("place")) return { "text-color": LABEL, "text-halo-color": HALO };
    return null;
  }
  if (id === "water") return { "fill-color": WATER };
  if (id === "waterway") return { "line-color": WATER };
  if (id.includes("park") || id.includes("wood")) return { "fill-color": PARK };
  if (id.startsWith("landuse") || id.startsWith("landcover")) return { "fill-color": LAND };
  if (id === "building") return { "fill-color": BUILDING, "fill-outline-color": LAND };
  if (id.startsWith("aeroway")) {
    return type === "fill" ? { "fill-color": "#313846" } : { "line-color": ROAD_SMALL };
  }
  if (id.startsWith("road_")) {
    return type === "fill" ? { "fill-color": LAND } : { "line-color": LAND };
  }
  if (id.startsWith("highway")) {
    if (id.endsWith("casing")) return { "line-color": ROAD_EDGE };
    if (id.includes("major_inner") || id.includes("motorway_inner")) return { "line-color": ROAD_BIG };
    if (id.includes("path")) return { "line-color": "#3b4252" };
    return { "line-color": ROAD_SMALL };
  }
  if (id.startsWith("railway")) {
    return { "line-color": id.endsWith("dashline") ? LAND : RAIL };
  }
  if (id.startsWith("boundary")) return { "line-color": "#5b6375" };
  return null;
}

interface StyleLayer {
  id: string;
  type: string;
  paint?: Paint;
  [key: string]: unknown;
}

interface StyleJson {
  layers: StyleLayer[];
  [key: string]: unknown;
}

function isStyle(value: unknown): value is StyleJson {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as { layers?: unknown }).layers)
  );
}

/** A copy of the style with our colours. The shaded-relief picture layer is dropped. */
export function recolour(style: StyleJson): StyleJson {
  const layers: StyleLayer[] = [];
  for (const layer of style.layers) {
    if (layer.type === "raster") continue;
    const paint = paintFor(layer.id, layer.type);
    layers.push(paint === null ? layer : { ...layer, paint: { ...layer.paint, ...paint } });
    if (layer.id === "landuse_park") {
      // The base style leaves lawns and city gardens uncoloured; phone maps show them green.
      layers.push({
        id: "landcover_grass",
        type: "fill",
        source: layer.source,
        "source-layer": "landcover",
        filter: ["==", ["get", "class"], "grass"],
        paint: { "fill-color": PARK },
      });
    }
  }
  return { ...style, layers };
}

/** The recoloured style, or the plain dark style's address if it cannot be prepared. */
export async function loadMapStyle(): Promise<StyleJson | string> {
  try {
    const response = await fetch(BASE_STYLE_URL);
    const style: unknown = await response.json();
    return response.ok && isStyle(style) ? recolour(style) : BASE_STYLE_URL;
  } catch {
    return BASE_STYLE_URL;
  }
}
