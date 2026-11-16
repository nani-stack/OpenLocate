// Pure helpers for the trip planner. No React, no map library, so they are easy to test.

import type { LatLon, Place, RoutePoint, RouteProfile } from "./rpc/types";

export const PROFILE_LABELS: Record<RouteProfile, string> = {
  walk: "Walk",
  bike: "Bike",
  drive: "Drive",
};

/** [west, south, east, north] around a path, or null for an empty one. */
export function pathBounds(path: readonly RoutePoint[]): [number, number, number, number] | null {
  if (path.length === 0) return null;
  let south = Infinity;
  let north = -Infinity;
  let west = Infinity;
  let east = -Infinity;
  for (const [lat, lon] of path) {
    south = Math.min(south, lat);
    north = Math.max(north, lat);
    west = Math.min(west, lon);
    east = Math.max(east, lon);
  }
  return [west, south, east, north];
}

/** What a route was computed for. Compared with the form to tell whether it is out of date. */
export interface RouteRequest {
  from: LatLon;
  to: LatLon;
  profile: RouteProfile;
}

export function sameRequest(a: RouteRequest | null, b: RouteRequest | null): boolean {
  if (a === null || b === null) return false;
  return (
    a.profile === b.profile &&
    a.from.lat === b.from.lat &&
    a.from.lon === b.from.lon &&
    a.to.lat === b.to.lat &&
    a.to.lon === b.to.lon
  );
}

/** The first part of a long address ("Tour Eiffel, 5, Avenue Anatole France" from a full line). */
export function shortPlaceName(place: Place, parts = 3): string {
  const pieces = place.name.split(",").map((piece) => piece.trim());
  return pieces.slice(0, parts).join(", ");
}

/** Time left on a trip, in seconds, from the playback progress (0..1). */
export function remainingSeconds(durationS: number, progress: number): number {
  const clamped = Math.min(1, Math.max(0, progress));
  return durationS * (1 - clamped);
}
