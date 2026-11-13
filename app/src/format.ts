// Formatting helpers for the playback readout.

/** Formats a 0..1 fraction as a percentage with one decimal. */
export function formatProgress(fraction: number): string {
  const clamped = Math.min(1, Math.max(0, fraction));
  return `${(clamped * 100).toFixed(1)} %`;
}

/** Formats metres as "850 m" below 1 km and "1.23 km" above. */
export function formatDistance(metres: number): string {
  if (Math.abs(metres) < 1000) {
    return `${Math.round(metres)} m`;
  }
  return `${(metres / 1000).toFixed(2)} km`;
}

export function formatSpeed(kmh: number): string {
  return `${kmh.toFixed(1)} km/h`;
}

/** Six decimals is about 0.1 m, more precise than any GPS fix. */
export function formatCoordinate(value: number): string {
  return value.toFixed(6);
}
