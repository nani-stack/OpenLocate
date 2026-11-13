// Input validation for the console. Invalid input never reaches the sidecar.

import type { LatLon } from "./rpc/types";

// Plain decimal numbers only: no exponents, hex, "Infinity" or empty strings.
const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;

export const MAX_SPEED_KMH = 540;

export type Validated<T> = { ok: true; value: T } | { ok: false; error: string };

export interface CoordinateErrors {
  lat?: string;
  lon?: string;
}

export type CoordinateResult = { ok: true; value: LatLon } | { ok: false; errors: CoordinateErrors };

/** Parses text as a plain decimal number within [min, max]. */
export function parseBoundedNumber(
  text: string,
  label: string,
  min: number,
  max: number,
): Validated<number> {
  const trimmed = text.trim();
  if (trimmed === "") {
    return { ok: false, error: `Enter a ${label}.` };
  }
  if (!DECIMAL.test(trimmed)) {
    return { ok: false, error: `${capitalise(label)} must be a number, like 48.8584.` };
  }
  const value = Number(trimmed);
  if (!Number.isFinite(value) || value < min || value > max) {
    return { ok: false, error: `${capitalise(label)} must be between ${min} and ${max}.` };
  }
  return { ok: true, value };
}

export function parseCoordinate(latText: string, lonText: string): CoordinateResult {
  const lat = parseBoundedNumber(latText, "latitude", -90, 90);
  const lon = parseBoundedNumber(lonText, "longitude", -180, 180);
  if (lat.ok && lon.ok) {
    return { ok: true, value: { lat: lat.value, lon: lon.value } };
  }
  const errors: CoordinateErrors = {};
  if (!lat.ok) errors.lat = lat.error;
  if (!lon.ok) errors.lon = lon.error;
  return { ok: false, errors };
}

/** Parses a custom speed in km/h: greater than 0 and at most 540 (the sidecar's limit). */
export function parseSpeedKmh(text: string): Validated<number> {
  const parsed = parseBoundedNumber(text, "speed", 0, MAX_SPEED_KMH);
  if (parsed.ok && parsed.value === 0) {
    return { ok: false, error: "Speed must be greater than 0." };
  }
  return parsed;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const SPEED_PRESETS_KMH = { walk: 5, bike: 16, drive: 50 } as const;

export type SpeedChoice = keyof typeof SPEED_PRESETS_KMH | "custom";

/** The speed for a selector choice; the custom text is only read for "custom". */
export function resolveSpeedKmh(choice: SpeedChoice, customText: string): Validated<number> {
  if (choice === "custom") {
    return parseSpeedKmh(customText);
  }
  return { ok: true, value: SPEED_PRESETS_KMH[choice] };
}
