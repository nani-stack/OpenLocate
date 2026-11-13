import { describe, expect, it, vi } from "vitest";

import { EXIT_EVENT, NOTIFICATION_EVENT, RpcClient, RpcError, toRpcError, type Transport } from "./client";

/** A fake transport: records invokes, answers with a scripted function, and lets tests emit events. */
class FakeTransport implements Transport {
  readonly invocations: { command: string; args: Record<string, unknown> | undefined }[] = [];
  readonly listeners = new Map<string, Set<(payload: unknown) => void>>();
  listenCalls = 0;

  constructor(private readonly answer: (command: string, args?: Record<string, unknown>) => unknown) {}

  invoke(command: string, args?: Record<string, unknown>): Promise<unknown> {
    this.invocations.push({ command, args });
    try {
      return Promise.resolve(this.answer(command, args));
    } catch (error) {
      return Promise.reject(error);
    }
  }

  listen(event: string, handler: (payload: unknown) => void): Promise<() => void> {
    this.listenCalls += 1;
    const set = this.listeners.get(event) ?? new Set();
    set.add(handler);
    this.listeners.set(event, set);
    return Promise.resolve(() => set.delete(handler));
  }

  emit(event: string, payload: unknown): void {
    for (const handler of this.listeners.get(event) ?? []) handler(payload);
  }
}

const STATUS = {
  state: "playing",
  distanceM: 12.5,
  lengthM: 1000,
  progress: 0.0125,
  speedKmh: 5,
  lap: 0,
  position: { lat: 1, lon: 2 },
};

describe("RpcClient.call", () => {
  it("invokes the rpc command with method and params and returns the result", async () => {
    const transport = new FakeTransport(() => ({ version: "0.1.0", backend: "mock", logFile: "/x.log" }));
    const client = new RpcClient(transport);

    const info = await client.call("app.info");

    expect(info).toEqual({ version: "0.1.0", backend: "mock", logFile: "/x.log" });
    expect(transport.invocations).toEqual([
      { command: "rpc", args: { method: "app.info", params: null } },
    ]);
  });

  it("passes params through unchanged", async () => {
    const transport = new FakeTransport(() => ({}));
    const client = new RpcClient(transport);

    await client.call("location.set", { lat: 48.8584, lon: 2.2945 });

    expect(transport.invocations[0]?.args).toEqual({
      method: "location.set",
      params: { lat: 48.8584, lon: 2.2945 },
    });
  });

  it("maps a structured error object to RpcError", async () => {
    const data = {
      code: "NOT_CONNECTED",
      message: "No iPhone is connected.",
      fix: "Connect an iPhone first.",
      detail: null,
    };
    const client = new RpcClient(new FakeTransport(() => { throw data; }));

    const error = await client.call("location.clear").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(RpcError);
    expect((error as RpcError).toData()).toEqual(data);
  });

  it("maps anything else to an INTERNAL RpcError with a fix", async () => {
    const client = new RpcClient(new FakeTransport(() => { throw "command rpc not found"; }));

    const error = (await client.call("app.info").catch((e: unknown) => e)) as RpcError;

    expect(error).toBeInstanceOf(RpcError);
    expect(error.code).toBe("INTERNAL");
    expect(error.message).not.toBe("");
    expect(error.fix).not.toBe("");
    expect(error.detail).toBe("command rpc not found");
  });

  it.each([
    ["an extra key", { version: "0.1.0", backend: "mock", logFile: "/x.log", extra: 1 }],
    ["a missing key", { version: "0.1.0", backend: "mock" }],
    ["a wrong type", { version: 1, backend: "mock", logFile: "/x.log" }],
    ["not an object", null],
  ])("rejects a result with %s as INTERNAL naming the method", async (_label, reply) => {
    const client = new RpcClient(new FakeTransport(() => reply));

    const error = (await client.call("app.info").catch((e: unknown) => e)) as RpcError;

    expect(error).toBeInstanceOf(RpcError);
    expect(error.code).toBe("INTERNAL");
    expect(error.message).toMatch(/unexpected reply/);
    expect(error.detail).toContain("app.info");
    expect(error.fix).not.toBe("");
  });

  it("rejects enum values outside the contract", async () => {
    const device = { id: "M", name: "n", model: "m", osVersion: "1", connection: "mock" };
    const ok = new RpcClient(new FakeTransport(() => ({ ...device, state: "ready" })));
    await expect(ok.call("device.connect", { id: "M" })).resolves.toMatchObject({ state: "ready" });
    const bad = new RpcClient(new FakeTransport(() => ({ ...device, state: "READY" })));
    await expect(bad.call("device.connect", { id: "M" })).rejects.toMatchObject({ code: "INTERNAL" });
  });

  it("restart invokes sidecar_restart and maps failures", async () => {
    const ok = new FakeTransport(() => undefined);
    await new RpcClient(ok).restart();
    expect(ok.invocations).toEqual([{ command: "sidecar_restart", args: undefined }]);

    const failing = new RpcClient(new FakeTransport(() => { throw new Error("boom"); }));
    await expect(failing.restart()).rejects.toMatchObject({ code: "INTERNAL", detail: "boom" });
  });
});

describe("toRpcError", () => {
  it("treats an error object without detail as malformed (INTERNAL)", () => {
    const error = toRpcError({ code: "X", message: "m", fix: "f" });
    expect(error.code).toBe("INTERNAL");
    expect(error.detail).toContain("\"code\":\"X\"");
  });

  it("returns an existing RpcError unchanged", () => {
    const original = new RpcError({ code: "X", message: "m", fix: "f", detail: null });
    expect(toRpcError(original)).toBe(original);
  });
});

describe("RpcClient notifications", () => {
  it("fans out each notification to every handler", () => {
    const transport = new FakeTransport(() => undefined);
    const client = new RpcClient(transport);
    const first = vi.fn();
    const second = vi.fn();
    client.onNotification(first);
    client.onNotification(second);

    transport.emit(NOTIFICATION_EVENT, { method: "playback.state", params: STATUS });

    const expected = { method: "playback.state", params: STATUS };
    expect(first).toHaveBeenCalledWith(expected);
    expect(second).toHaveBeenCalledWith(expected);
  });

  it("subscribes to the transport only once", () => {
    const transport = new FakeTransport(() => undefined);
    const client = new RpcClient(transport);
    client.onNotification(vi.fn());
    client.onNotification(vi.fn());
    client.onExit(vi.fn());

    expect(transport.listenCalls).toBe(2);
  });

  it("stops calling a handler after unsubscribe", () => {
    const transport = new FakeTransport(() => undefined);
    const client = new RpcClient(transport);
    const kept = vi.fn();
    const removed = vi.fn();
    client.onNotification(kept);
    const unsubscribe = client.onNotification(removed);

    unsubscribe();
    transport.emit(NOTIFICATION_EVENT, {
      method: "location.updated",
      params: { lat: 1, lon: 2, source: "teleport" },
    });

    expect(kept).toHaveBeenCalledTimes(1);
    expect(removed).not.toHaveBeenCalled();
  });

  it("ignores unknown or malformed notifications", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const transport = new FakeTransport(() => undefined);
    const client = new RpcClient(transport);
    const handler = vi.fn();
    client.onNotification(handler);

    transport.emit(NOTIFICATION_EVENT, { method: "schedule.fired", params: {} });
    transport.emit(NOTIFICATION_EVENT, { method: "location.updated", params: { lat: "1", lon: 2 } });
    transport.emit(NOTIFICATION_EVENT, { method: "playback.state", params: { state: "PLAYING" } });
    transport.emit(NOTIFICATION_EVENT, "not an object");

    expect(handler).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledTimes(4);
    warn.mockRestore();
  });

  it("rejects notifications with extra or missing keys", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const transport = new FakeTransport(() => undefined);
    const client = new RpcClient(transport);
    const handler = vi.fn();
    client.onNotification(handler);

    transport.emit(NOTIFICATION_EVENT, {
      method: "playback.error",
      params: { code: "DEVICE_DISCONNECTED", message: "m", fix: "f" },
    });
    transport.emit(NOTIFICATION_EVENT, {
      method: "location.updated",
      params: { lat: 1, lon: 2, source: "teleport", extra: true },
    });
    transport.emit(NOTIFICATION_EVENT, { method: "playback.state", params: STATUS, extra: 1 });

    expect(handler).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("reports sidecar exit with its code, or null when unknown", () => {
    const transport = new FakeTransport(() => undefined);
    const client = new RpcClient(transport);
    const handler = vi.fn();
    const unsubscribe = client.onExit(handler);

    transport.emit(EXIT_EVENT, { code: 3 });
    transport.emit(EXIT_EVENT, { code: null });
    unsubscribe();
    transport.emit(EXIT_EVENT, { code: 1 });

    expect(handler.mock.calls).toEqual([[{ code: 3 }], [{ code: null }]]);
  });
});
