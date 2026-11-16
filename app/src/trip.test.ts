import { describe, expect, it } from "vitest";

import { pathBounds, remainingSeconds, sameRequest, shortPlaceName, type RouteRequest } from "./trip";

describe("trip helpers", () => {
  it("finds the box around a path as west, south, east, north", () => {
    expect(pathBounds([])).toBeNull();
    expect(
      pathBounds([
        [48.8584, 2.2945],
        [48.8616, 2.2893],
        [48.8738, 2.295],
      ]),
    ).toEqual([2.2893, 48.8584, 2.295, 48.8738]);
  });

  it("tells whether a route still matches the form", () => {
    const request: RouteRequest = {
      from: { lat: 1, lon: 2 },
      to: { lat: 3, lon: 4 },
      profile: "walk",
    };
    expect(sameRequest(request, { ...request })).toBe(true);
    expect(sameRequest(request, { ...request, profile: "drive" })).toBe(false);
    expect(sameRequest(request, { ...request, to: { lat: 3, lon: 5 } })).toBe(false);
    expect(sameRequest(null, request)).toBe(false);
  });

  it("shortens a long address to its first parts", () => {
    const place = { name: "Tour Eiffel, 5, Avenue Anatole France, Paris, France", lat: 0, lon: 0 };
    expect(shortPlaceName(place)).toBe("Tour Eiffel, 5, Avenue Anatole France");
    expect(shortPlaceName({ ...place, name: "Paris" })).toBe("Paris");
  });

  it("works out the time left from the progress", () => {
    expect(remainingSeconds(600, 0)).toBe(600);
    expect(remainingSeconds(600, 0.25)).toBe(450);
    expect(remainingSeconds(600, 1.4)).toBe(0);
    expect(remainingSeconds(600, -1)).toBe(600);
  });
});
