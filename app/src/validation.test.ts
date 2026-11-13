import { describe, expect, it } from "vitest";

import { parseCoordinate, parseSpeedKmh, resolveSpeedKmh } from "./validation";

describe("parseCoordinate", () => {
  it("accepts valid coordinates, including the limits and surrounding spaces", () => {
    expect(parseCoordinate("48.8584", "2.2945")).toEqual({ ok: true, value: { lat: 48.8584, lon: 2.2945 } });
    expect(parseCoordinate("-90", "180")).toEqual({ ok: true, value: { lat: -90, lon: 180 } });
    expect(parseCoordinate(" 90 ", "-180.0")).toEqual({ ok: true, value: { lat: 90, lon: -180 } });
    expect(parseCoordinate(".5", "+1.")).toEqual({ ok: true, value: { lat: 0.5, lon: 1 } });
  });

  it("rejects out-of-range values", () => {
    const result = parseCoordinate("90.0001", "-180.5");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.lat).toMatch(/between -90 and 90/);
      expect(result.errors.lon).toMatch(/between -180 and 180/);
    }
  });

  it.each(["", "   ", "abc", "12abc", "1e3", "0x10", "Infinity", "NaN", "1,5", "--1", "."])(
    "rejects non-numeric latitude %j",
    (text) => {
      const result = parseCoordinate(text, "0");
      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.errors.lat).toBeDefined();
        expect(result.errors.lon).toBeUndefined();
      }
    },
  );

  it("reports only the longitude when only it is wrong", () => {
    const result = parseCoordinate("10", "east");
    expect(result).toEqual({ ok: false, errors: { lon: "Longitude must be a number, like 48.8584." } });
  });
});

describe("speed", () => {
  it("accepts a custom speed above 0 and up to 540 km/h", () => {
    expect(parseSpeedKmh("30")).toEqual({ ok: true, value: 30 });
    expect(parseSpeedKmh("540")).toEqual({ ok: true, value: 540 });
  });

  it.each(["0", "-5", "541", "", "fast"])("rejects custom speed %j", (text) => {
    expect(parseSpeedKmh(text).ok).toBe(false);
  });

  it("resolves presets without reading the custom text", () => {
    expect(resolveSpeedKmh("walk", "junk")).toEqual({ ok: true, value: 5 });
    expect(resolveSpeedKmh("bike", "")).toEqual({ ok: true, value: 16 });
    expect(resolveSpeedKmh("drive", "")).toEqual({ ok: true, value: 50 });
    expect(resolveSpeedKmh("custom", "12.5")).toEqual({ ok: true, value: 12.5 });
    expect(resolveSpeedKmh("custom", "").ok).toBe(false);
  });
});
