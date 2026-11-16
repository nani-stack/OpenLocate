import { describe, expect, it } from "vitest";

import { paintFor, recolour } from "./mapStyle";

describe("map style", () => {
  it("recolours the layers it knows and leaves the others alone", () => {
    expect(paintFor("background", "background")).toEqual({ "background-color": "#2a2f3b" });
    expect(paintFor("water", "fill")).toEqual({ "fill-color": "#17264d" });
    expect(paintFor("landuse_park", "fill")).toEqual({ "fill-color": "#1e4032" });
    expect(paintFor("highway_major_casing", "line")).toEqual({ "line-color": "#20242d" });
    expect(paintFor("highway_major_inner", "line")).toEqual({ "line-color": "#5d6679" });
    expect(paintFor("road_oneway", "symbol")).toBeNull();
    expect(paintFor("something_new", "fill")).toBeNull();
  });

  it("keeps other paint settings, drops picture layers and does not change its input", () => {
    const style = {
      version: 8,
      layers: [
        { id: "relief", type: "raster" },
        { id: "highway_minor", type: "line", paint: { "line-color": "#181818", "line-width": 2 } },
        { id: "road_oneway", type: "symbol" },
      ],
    };
    const result = recolour(style);
    expect(result.version).toBe(8);
    expect(result.layers.map((layer) => layer.id)).toEqual(["highway_minor", "road_oneway"]);
    expect(result.layers[0]?.paint).toEqual({ "line-color": "#454d5f", "line-width": 2 });
    expect(style.layers[1]?.paint).toEqual({ "line-color": "#181818", "line-width": 2 });
  });

  it("adds green lawns right after the parks layer", () => {
    const style = {
      layers: [
        { id: "landuse_park", type: "fill", source: "openmaptiles" },
        { id: "building", type: "fill" },
      ],
    };
    const ids = recolour(style).layers.map((layer) => layer.id);
    expect(ids).toEqual(["landuse_park", "landcover_grass", "building"]);
  });
});
