import { describe, expect, it } from "vitest";

import { DEMO_ROUTE } from "./demoRoute";
import type { RoutePoint } from "./rpc/types";

const EARTH_RADIUS_M = 6_371_008.8;

function haversineM([lat1, lon1]: RoutePoint, [lat2, lon2]: RoutePoint): number {
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad;
  const dLon = (lon2 - lon1) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

describe("DEMO_ROUTE", () => {
  it("has 8 to 12 points and is about 1 km long", () => {
    expect(DEMO_ROUTE.length).toBeGreaterThanOrEqual(8);
    expect(DEMO_ROUTE.length).toBeLessThanOrEqual(12);
    let length = 0;
    for (let i = 1; i < DEMO_ROUTE.length; i++) {
      length += haversineM(DEMO_ROUTE[i - 1]!, DEMO_ROUTE[i]!);
    }
    expect(length).toBeGreaterThan(800);
    expect(length).toBeLessThan(1200);
  });
});
