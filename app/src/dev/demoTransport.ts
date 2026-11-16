// A stand-in sidecar for `npm run dev` in a plain browser, where Tauri and the real sidecar
// do not exist. It only makes the screens usable for layout work: places and routes are made
// up, and nothing reaches a device or the network. The real app never loads this file.

import { NOTIFICATION_EVENT, type Transport } from "../rpc/client";
import type { DeviceInfo, PlaybackStatus, RoutePoint } from "../rpc/types";

type Handler = (payload: unknown) => void;

const PLACES: Record<string, { name: string; lat: number; lon: number }[]> = {
  eiffel: [{ name: "Tour Eiffel, Avenue Gustave Eiffel, Paris, France", lat: 48.8584, lon: 2.2945 }],
  arc: [{ name: "Arc de Triomphe, Place Charles de Gaulle, Paris, France", lat: 48.8738, lon: 2.295 }],
  paris: [
    { name: "Paris, Île-de-France, France", lat: 48.8566, lon: 2.3522 },
    { name: "Paris, Lamar County, Texas, United States", lat: 33.6609, lon: -95.5555 },
  ],
};

const SPEED_KMH = { walk: 4.5, bike: 15, drive: 300 } as const;

function metres(a: RoutePoint, b: RoutePoint): number {
  const dLat = (b[0] - a[0]) * 111_320;
  const dLon = (b[1] - a[1]) * 111_320 * Math.cos((a[0] * Math.PI) / 180);
  return Math.hypot(dLat, dLon);
}

export function createDemoTransport(): Transport {
  const listeners = new Map<string, Set<Handler>>();
  const device: DeviceInfo = {
    id: "DEMO-0001",
    name: "Demo iPhone",
    model: "Browser preview",
    osVersion: "27.2",
    connection: "mock",
    state: "disconnected",
  };
  let path: RoutePoint[] = [];
  let lengthM = 0;
  let speedKmh = 5;
  let distanceM = 0;
  let state: PlaybackStatus["state"] = "idle";
  let loaded = false;
  let timer: ReturnType<typeof setInterval> | undefined;

  const emit = (method: string, params: unknown) => {
    for (const handler of listeners.get(NOTIFICATION_EVENT) ?? []) handler({ method, params });
  };

  const positionAt = (d: number): RoutePoint => {
    let walked = 0;
    for (let i = 1; i < path.length; i++) {
      const a = path[i - 1] as RoutePoint;
      const b = path[i] as RoutePoint;
      const step = metres(a, b);
      if (walked + step >= d && step > 0) {
        const t = (d - walked) / step;
        return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      }
      walked += step;
    }
    return path[path.length - 1] ?? [0, 0];
  };

  const status = (): PlaybackStatus => {
    const at = loaded && state !== "idle" ? positionAt(distanceM) : null;
    return {
      state,
      distanceM,
      lengthM,
      progress: lengthM > 0 ? distanceM / lengthM : 0,
      speedKmh,
      lap: 0,
      position: at === null ? null : { lat: at[0], lon: at[1] },
    };
  };

  const stopTimer = () => {
    clearInterval(timer);
    timer = undefined;
  };

  const tick = () => {
    if (state !== "playing") return;
    distanceM = Math.min(lengthM, distanceM + speedKmh / 3.6);
    const [lat, lon] = positionAt(distanceM);
    emit("location.updated", { lat, lon, source: "playback" });
    if (distanceM >= lengthM) {
      state = "finished";
      stopTimer();
      emit("playback.state", status());
    }
  };

  const fail = (code: string, message: string, fix: string) =>
    Promise.reject({ code, message, fix, detail: "browser preview" });

  const rpc = (method: string, params: Record<string, unknown> | null): Promise<unknown> => {
    switch (method) {
      case "app.info":
        return Promise.resolve({ version: "preview", backend: "browser demo", logFile: "(none)" });
      case "device.list":
        return Promise.resolve({ devices: [device] });
      case "device.connect":
        device.state = "ready";
        return Promise.resolve({ ...device });
      case "device.disconnect":
        device.state = "disconnected";
        return Promise.resolve({});
      case "search.find": {
        const query = String(params?.query ?? "").toLowerCase();
        const key = Object.keys(PLACES).find((k) => query.includes(k));
        return Promise.resolve({ results: key ? PLACES[key] : [] });
      }
      case "playback.loadRoute": {
        const [a, b] = params?.waypoints as [RoutePoint, RoutePoint];
        const profile = params?.profile as keyof typeof SPEED_KMH;
        const corner: RoutePoint = [a[0], b[1]];
        path = [a, [a[0], (a[1] + b[1]) / 2 + 0.004], corner, [(a[0] + b[0]) / 2, b[1] + 0.003], b];
        lengthM = path.slice(1).reduce((sum, p, i) => sum + metres(path[i] as RoutePoint, p), 0);
        if (lengthM === 0) {
          return fail("NO_ROUTE_FOUND", "No route could be found.", "Pick two different places.");
        }
        speedKmh = SPEED_KMH[profile];
        distanceM = 0;
        state = "idle";
        loaded = true;
        stopTimer();
        return Promise.resolve({
          lengthM,
          points: path.length,
          durationS: lengthM / (speedKmh / 3.6),
          speedKmh,
          path,
        });
      }
      case "playback.start":
        if (!loaded) return fail("NO_ROUTE_LOADED", "No route is loaded.", "Get a route first.");
        if (device.state !== "ready") {
          return fail("NOT_CONNECTED", "No iPhone is connected.", "Connect a device first.");
        }
        distanceM = 0;
        state = "playing";
        stopTimer();
        timer = setInterval(tick, 1000);
        emit("location.updated", { lat: (path[0] as RoutePoint)[0], lon: (path[0] as RoutePoint)[1], source: "playback" });
        return Promise.resolve(status());
      case "playback.pause":
        state = "paused";
        return Promise.resolve(status());
      case "playback.resume":
        state = "playing";
        return Promise.resolve(status());
      case "playback.stop":
        state = "idle";
        distanceM = 0;
        stopTimer();
        return Promise.resolve(status());
      case "playback.status":
        return Promise.resolve(status());
      case "location.set":
        emit("location.updated", { lat: params?.lat, lon: params?.lon, source: "teleport" });
        return Promise.resolve({});
      case "location.clear":
        return Promise.resolve({});
      default:
        return fail("INTERNAL", `The preview has no ${method}.`, "Run the real app.");
    }
  };

  return {
    invoke(command, args) {
      if (command === "rpc") {
        return rpc(String(args?.method), (args?.params ?? null) as Record<string, unknown> | null);
      }
      return Promise.resolve(null);
    },
    listen(event, handler) {
      const set = listeners.get(event) ?? new Set<Handler>();
      listeners.set(event, set);
      set.add(handler);
      return Promise.resolve(() => set.delete(handler));
    },
  };
}
