// Checks the TypeScript guards and enums against protocol/contract.json, the shared wire
// contract that the sidecar's tests replay as well. A missing contract file fails the test.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { isNotification, isRpcErrorData, RESULT_GUARDS } from "./guards";
import {
  CONNECTIONS,
  DEVICE_STATES,
  LOCATION_SOURCES,
  PLAYBACK_STATES,
  ROUTE_PROFILES,
  type MethodName,
} from "./types";

const CONTRACT_URL = new URL("../../../protocol/contract.json", import.meta.url);

interface SessionStep {
  name: string;
  request: { method: string; params?: unknown };
  result?: unknown;
  error?: unknown;
  notifications?: unknown[];
}

interface Contract {
  enums: Record<string, string[]>;
  session: SessionStep[];
  notifications: unknown[];
}

const contract = JSON.parse(readFileSync(CONTRACT_URL, "utf8")) as Contract;

// Sample values for the contract's placeholders (see its $comment).
const SAMPLES: Record<string, unknown> = {
  "<string>": "sample",
  "<number>": 12.5,
  "<int>": 2,
  "<bool>": true,
  "<latlon>": { lat: 48.8584, lon: 2.2945 },
};

/** Replaces placeholders recursively with sample values of the right type. */
function fill(value: unknown): unknown {
  if (typeof value === "string" && value in SAMPLES) return SAMPLES[value];
  if (Array.isArray(value)) return value.map(fill);
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, fill(v)]));
  }
  return value;
}

function isMethodName(method: string): method is MethodName {
  return Object.hasOwn(RESULT_GUARDS, method);
}

describe("protocol contract", () => {
  it("has a session with results, errors and notifications", () => {
    expect(contract.session.some((s) => s.result !== undefined)).toBe(true);
    expect(contract.session.some((s) => s.error !== undefined)).toBe(true);
    expect(contract.notifications.length).toBeGreaterThan(0);
  });

  it.each(contract.session.filter((s) => s.result !== undefined).map((s) => [s.name, s] as const))(
    "result of step %j passes its method's guard",
    (_name, step) => {
      const method = step.request.method;
      expect(isMethodName(method), `unknown method ${method}`).toBe(true);
      if (isMethodName(method)) {
        expect(RESULT_GUARDS[method](fill(step.result))).toBe(true);
      }
    },
  );

  it.each(contract.session.filter((s) => s.error !== undefined).map((s) => [s.name, s] as const))(
    "error of step %j passes the error guard",
    (_name, step) => {
      expect(isRpcErrorData(fill(step.error))).toBe(true);
    },
  );

  it("every notification passes the notification guard", () => {
    const all = [
      ...contract.session.flatMap((s) => s.notifications ?? []),
      ...contract.notifications,
    ];
    expect(all.length).toBeGreaterThan(contract.notifications.length);
    for (const notification of all) {
      expect(isNotification(fill(notification)), JSON.stringify(notification)).toBe(true);
    }
  });

  it("enums equal the TypeScript lists exactly", () => {
    expect(contract.enums.deviceState).toEqual([...DEVICE_STATES]);
    expect(contract.enums.connection).toEqual([...CONNECTIONS]);
    expect(contract.enums.playbackState).toEqual([...PLAYBACK_STATES]);
    expect(contract.enums.locationSource).toEqual([...LOCATION_SOURCES]);
    expect(contract.enums.routeProfile).toEqual([...ROUTE_PROFILES]);
  });

  it("the guards are strict: an extra key fails", () => {
    const step = contract.session.find((s) => s.request.method === "app.info");
    const result = { ...(fill(step?.result) as object), extra: true };
    expect(RESULT_GUARDS["app.info"](result)).toBe(false);
  });
});
