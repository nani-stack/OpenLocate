// TypeScript mirror of the sidecar's JSON-RPC contract.
// Source of truth: the method table in docs/specs/m1-sidecar-core.md.
// JSON field names are camelCase on the wire.

export interface LatLon {
  lat: number;
  lon: number;
}

// Enum values, exactly as listed in protocol/contract.json (`enums`). The contract test checks
// that these arrays and the contract stay identical.
export const DEVICE_STATES = [
  "disconnected",
  "connecting",
  "needs_trust",
  "needs_developer_mode",
  "mounting_image",
  "ready",
  "error",
] as const;
export const CONNECTIONS = ["usb", "wifi", "mock"] as const;
export const PLAYBACK_STATES = ["idle", "playing", "paused", "finished"] as const;
export const LOCATION_SOURCES = ["teleport", "playback"] as const;
export const ROUTE_PROFILES = ["walk", "bike", "drive"] as const;

export type DeviceState = (typeof DEVICE_STATES)[number];
export type Connection = (typeof CONNECTIONS)[number];
export type PlaybackState = (typeof PLAYBACK_STATES)[number];
export type LocationSource = (typeof LOCATION_SOURCES)[number];
export type RouteProfile = (typeof ROUTE_PROFILES)[number];

export interface DeviceInfo {
  id: string;
  name: string;
  model: string;
  osVersion: string;
  connection: Connection;
  state: DeviceState;
}

export interface PlaybackStatus {
  state: PlaybackState;
  distanceM: number;
  lengthM: number;
  progress: number;
  speedKmh: number;
  lap: number;
  position: LatLon | null;
}

export interface AppInfo {
  version: string;
  backend: string;
  logFile: string;
}

/** The error object every failed call rejects with. Mirrors `OpenLocateError.to_dict()`. */
export interface RpcErrorData {
  code: string;
  message: string;
  fix: string;
  detail: string | null;
}

export type EmptyResult = Record<string, never>;

/** Points as `[lat, lon]` pairs, the shape `playback.load` expects. */
export type RoutePoint = [lat: number, lon: number];

export interface PlaybackLoadParams {
  points: RoutePoint[];
  speedKmh: number;
  loop?: boolean;
  jitter?: boolean;
}

/** Waypoints the sidecar joins along real roads. Without `speedKmh` the trip is played at
 * the routing service's own average speed for that profile. */
export interface PlaybackLoadRouteParams {
  waypoints: RoutePoint[];
  profile: RouteProfile;
  speedKmh?: number;
  loop?: boolean;
  jitter?: boolean;
}

export interface LoadedRoadRoute {
  lengthM: number;
  points: number;
  durationS: number;
  speedKmh: number;
}

/** Every RPC method: its params (`undefined` when it takes none) and its result. */
export interface Methods {
  "app.info": { params: undefined; result: AppInfo };
  "device.list": { params: undefined; result: { devices: DeviceInfo[] } };
  "device.connect": { params: { id: string }; result: DeviceInfo };
  "device.disconnect": { params: undefined; result: EmptyResult };
  "location.set": { params: LatLon; result: EmptyResult };
  "location.clear": { params: undefined; result: EmptyResult };
  "playback.load": { params: PlaybackLoadParams; result: { lengthM: number; points: number } };
  "playback.loadRoute": { params: PlaybackLoadRouteParams; result: LoadedRoadRoute };
  "playback.start": { params: undefined; result: PlaybackStatus };
  "playback.pause": { params: undefined; result: PlaybackStatus };
  "playback.resume": { params: undefined; result: PlaybackStatus };
  "playback.stop": { params: undefined; result: PlaybackStatus };
  "playback.setSpeed": { params: { speedKmh: number }; result: PlaybackStatus };
  "playback.status": { params: undefined; result: PlaybackStatus };
}

export type MethodName = keyof Methods;
export type ParamsOf<M extends MethodName> = Methods[M]["params"];
export type ResultOf<M extends MethodName> = Methods[M]["result"];

/** Notifications the sidecar sends (JSON-RPC messages without an id). */
export type SidecarNotification =
  | { method: "location.updated"; params: LatLon & { source: LocationSource } }
  | { method: "playback.state"; params: PlaybackStatus }
  | { method: "playback.error"; params: RpcErrorData };

/** Payload of the `sidecar://exit` event emitted by the Rust shell. */
export interface SidecarExit {
  code: number | null;
}
