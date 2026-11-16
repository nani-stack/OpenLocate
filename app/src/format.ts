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

/** Formats seconds as "45 s", "12 min" or "1 h 05 min". */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) {
    return `${total} s`;
  }
  const minutes = Math.round(total / 60);
  if (minutes < 60) {
    return `${minutes} min`;
  }
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
}

export function formatSpeed(kmh: number): string {
  return `${kmh.toFixed(1)} km/h`;
}

/** Six decimals is about 0.1 m, more precise than any GPS fix. */
export function formatCoordinate(value: number): string {
  return value.toFixed(6);
}
