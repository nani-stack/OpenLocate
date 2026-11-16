import { describe, expect, it } from "vitest";

import {
  formatCoordinate,
  formatDistance,
  formatDuration,
  formatProgress,
  formatSpeed,
} from "./format";

describe("format", () => {
  it("formats progress, clamped to 0..100 %", () => {
    expect(formatProgress(0.4567)).toBe("45.7 %");
    expect(formatProgress(-1)).toBe("0.0 %");
    expect(formatProgress(2)).toBe("100.0 %");
  });

  it("formats distances in m and km", () => {
    expect(formatDistance(850.4)).toBe("850 m");
    expect(formatDistance(1234)).toBe("1.23 km");
  });

  it("formats speed and coordinates", () => {
    expect(formatSpeed(5)).toBe("5.0 km/h");
    expect(formatCoordinate(48.85837)).toBe("48.858370");
  });

  it("formats durations in seconds, minutes, then hours", () => {
    expect(formatDuration(0)).toBe("0 s");
    expect(formatDuration(45.4)).toBe("45 s");
    expect(formatDuration(393.3)).toBe("7 min");
    expect(formatDuration(1797.5)).toBe("30 min");
    expect(formatDuration(3900)).toBe("1 h 05 min");
    expect(formatDuration(-5)).toBe("0 s");
  });
});
