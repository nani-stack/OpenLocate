// Runtime checks for everything that crosses the process boundary from the sidecar.
// Rule from protocol/contract.json: objects have exactly the listed keys, no more, no fewer.

import {
  CONNECTIONS,
  DEVICE_STATES,
  LOCATION_SOURCES,
  PLAYBACK_STATES,
  type AppInfo,
  type DeviceInfo,
  type EmptyResult,
  type LatLon,
  type LoadedRoadRoute,
  type MethodName,
  type Place,
  type PlaybackStatus,
  type ResultOf,
  type RpcErrorData,
  type SidecarNotification,
} from "./types";

export type Guard<T> = (value: unknown) => value is T;

type Shape<T> = { [K in keyof T]-?: Guard<T[K]> };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** An object with exactly the keys of `shape`, each passing its guard. */
export function exactObject<T>(shape: Shape<T>): Guard<T> {
  const keys = Object.keys(shape) as (keyof T & string)[];
  return (value: unknown): value is T => {
    if (!isRecord(value)) return false;
    const actual = Object.keys(value);
    if (actual.length !== keys.length) return false;
    return keys.every((key) => Object.hasOwn(value, key) && shape[key](value[key]));
  };
}

export const isString: Guard<string> = (v): v is string => typeof v === "string";
export const isFiniteNumber: Guard<number> = (v): v is number =>
  typeof v === "number" && Number.isFinite(v);
const isInteger: Guard<number> = (v): v is number => Number.isInteger(v);

function oneOf<T extends string>(values: readonly T[]): Guard<T> {
  return (v): v is T => typeof v === "string" && (values as readonly string[]).includes(v);
}

function nullable<T>(guard: Guard<T>): Guard<T | null> {
  return (v): v is T | null => v === null || guard(v);
}

function arrayOf<T>(guard: Guard<T>): Guard<T[]> {
  return (v): v is T[] => Array.isArray(v) && v.every((item) => guard(item));
}

export const isLatLon: Guard<LatLon> = exactObject<LatLon>({ lat: isFiniteNumber, lon: isFiniteNumber });

export const isEmptyResult: Guard<EmptyResult> = exactObject<EmptyResult>({});

export const isAppInfo: Guard<AppInfo> = exactObject<AppInfo>({
  version: isString,
  backend: isString,
  logFile: isString,
});

export const isDeviceInfo: Guard<DeviceInfo> = exactObject<DeviceInfo>({
  id: isString,
  name: isString,
  model: isString,
  osVersion: isString,
  connection: oneOf(CONNECTIONS),
  state: oneOf(DEVICE_STATES),
});

export const isPlaybackStatus: Guard<PlaybackStatus> = exactObject<PlaybackStatus>({
  state: oneOf(PLAYBACK_STATES),
  distanceM: isFiniteNumber,
  lengthM: isFiniteNumber,
  progress: isFiniteNumber,
  speedKmh: isFiniteNumber,
  lap: isInteger,
  position: nullable(isLatLon),
});

export const isRpcErrorData: Guard<RpcErrorData> = exactObject<RpcErrorData>({
  code: isString,
  message: isString,
  fix: isString,
  detail: nullable(isString),
});

const isRoutePoint: Guard<[number, number]> = (v): v is [number, number] =>
  Array.isArray(v) && v.length === 2 && isFiniteNumber(v[0]) && isFiniteNumber(v[1]);

const isPlace: Guard<Place> = exactObject<Place>({
  name: isString,
  lat: isFiniteNumber,
  lon: isFiniteNumber,
});

/** One guard per method, for the method's `result`. */
export const RESULT_GUARDS: { [M in MethodName]: Guard<ResultOf<M>> } = {
  "app.info": isAppInfo,
  "device.list": exactObject<{ devices: DeviceInfo[] }>({ devices: arrayOf(isDeviceInfo) }),
  "device.connect": isDeviceInfo,
  "device.disconnect": isEmptyResult,
  "location.set": isEmptyResult,
  "location.clear": isEmptyResult,
  "search.find": exactObject<{ results: Place[] }>({ results: arrayOf(isPlace) }),
  "playback.load": exactObject<{ lengthM: number; points: number }>({
    lengthM: isFiniteNumber,
    points: isInteger,
  }),
  "playback.loadRoute": exactObject<LoadedRoadRoute>({
    lengthM: isFiniteNumber,
    points: isInteger,
    durationS: isFiniteNumber,
    speedKmh: isFiniteNumber,
    path: arrayOf(isRoutePoint),
  }),
  "playback.start": isPlaybackStatus,
  "playback.pause": isPlaybackStatus,
  "playback.resume": isPlaybackStatus,
  "playback.stop": isPlaybackStatus,
  "playback.setSpeed": isPlaybackStatus,
  "playback.status": isPlaybackStatus,
};

type LocationUpdated = Extract<SidecarNotification, { method: "location.updated" }>["params"];

const isLocationUpdated: Guard<LocationUpdated> = exactObject<LocationUpdated>({
  lat: isFiniteNumber,
  lon: isFiniteNumber,
  source: oneOf(LOCATION_SOURCES),
});

/** A `{method, params}` notification as forwarded by the Rust shell. */
export const isNotification: Guard<SidecarNotification> = (v): v is SidecarNotification => {
  if (!isRecord(v) || Object.keys(v).length !== 2 || !Object.hasOwn(v, "params")) {
    return false;
  }
  switch (v.method) {
    case "location.updated":
      return isLocationUpdated(v.params);
    case "playback.state":
      return isPlaybackStatus(v.params);
    case "playback.error":
      return isRpcErrorData(v.params);
    default:
      return false;
  }
};
