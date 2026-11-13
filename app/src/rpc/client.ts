// Typed client for the sidecar. The transport (Tauri's invoke/listen in the app, a fake in
// tests) is injected, so nothing here depends on Tauri.

import { isNotification, isRpcErrorData, RESULT_GUARDS } from "./guards";
import type {
  MethodName,
  ParamsOf,
  ResultOf,
  RpcErrorData,
  SidecarExit,
  SidecarNotification,
} from "./types";

export const NOTIFICATION_EVENT = "sidecar://notification";
export const EXIT_EVENT = "sidecar://exit";

export type Unsubscribe = () => void;

export interface Transport {
  invoke(command: string, args?: Record<string, unknown>): Promise<unknown>;
  listen(event: string, handler: (payload: unknown) => void): Promise<Unsubscribe>;
}

/** A failed call. `code`, `message` and `fix` are always present and human-readable. */
export class RpcError extends Error {
  readonly code: string;
  readonly fix: string;
  readonly detail: string | null;

  constructor(data: RpcErrorData) {
    super(data.message);
    this.name = "RpcError";
    this.code = data.code;
    this.fix = data.fix;
    this.detail = data.detail;
  }

  toData(): RpcErrorData {
    return { code: this.code, message: this.message, fix: this.fix, detail: this.detail };
  }
}

const FALLBACK_FIX =
  "Restart the sidecar with the Restart button. If it keeps happening, report it with the log file.";

/** Turns anything a failed invoke rejects with into an `RpcError`. */
export function toRpcError(reason: unknown): RpcError {
  if (reason instanceof RpcError) {
    return reason;
  }
  if (isRpcErrorData(reason)) {
    return new RpcError(reason);
  }
  const detail = reason instanceof Error ? reason.message : stringify(reason);
  return new RpcError({
    code: "INTERNAL",
    message: "The app could not talk to the sidecar.",
    fix: FALLBACK_FIX,
    detail,
  });
}

type ArgsFor<M extends MethodName> = ParamsOf<M> extends undefined ? [] : [params: ParamsOf<M>];

type NotificationHandler = (notification: SidecarNotification) => void;
type ExitHandler = (exit: SidecarExit) => void;

export class RpcClient {
  private readonly transport: Transport;
  private readonly notificationHandlers = new Set<NotificationHandler>();
  private readonly exitHandlers = new Set<ExitHandler>();
  private subscribed = false;

  constructor(transport: Transport) {
    this.transport = transport;
  }

  /** Calls a sidecar method. Rejects with `RpcError` on any failure. */
  async call<M extends MethodName>(method: M, ...args: ArgsFor<M>): Promise<ResultOf<M>> {
    const params = args[0];
    let result: unknown;
    try {
      result = await this.transport.invoke("rpc", {
        method,
        params: params === undefined ? null : params,
      });
    } catch (reason) {
      throw toRpcError(reason);
    }
    // Widened to a plain Guard so TypeScript does not intersect every method's guard type.
    const guard: (value: unknown) => value is ResultOf<M> = RESULT_GUARDS[method];
    if (!guard(result)) {
      throw new RpcError({
        code: "INTERNAL",
        message: "The sidecar sent an unexpected reply.",
        fix: FALLBACK_FIX,
        detail: `Reply to ${method} does not match the protocol contract.`,
      });
    }
    return result;
  }

  /** Kills the sidecar (if running) and starts a new one. */
  async restart(): Promise<void> {
    try {
      await this.transport.invoke("sidecar_restart");
    } catch (reason) {
      throw toRpcError(reason);
    }
  }

  /** Registers a handler for sidecar notifications. Returns a function that removes it. */
  onNotification(handler: NotificationHandler): Unsubscribe {
    this.ensureSubscribed();
    this.notificationHandlers.add(handler);
    return () => {
      this.notificationHandlers.delete(handler);
    };
  }

  /** Registers a handler called when the sidecar process exits. Returns a function that removes it. */
  onExit(handler: ExitHandler): Unsubscribe {
    this.ensureSubscribed();
    this.exitHandlers.add(handler);
    return () => {
      this.exitHandlers.delete(handler);
    };
  }

  // The transport is subscribed once; handlers are fanned out here, so `onNotification` can
  // return its unsubscribe function synchronously.
  private ensureSubscribed(): void {
    if (this.subscribed) {
      return;
    }
    this.subscribed = true;
    const failed = (event: string) => (reason: unknown) => {
      console.error(`Could not subscribe to ${event}:`, reason);
    };
    this.transport
      .listen(NOTIFICATION_EVENT, (payload) => this.dispatchNotification(payload))
      .catch(failed(NOTIFICATION_EVENT));
    this.transport
      .listen(EXIT_EVENT, (payload) => this.dispatchExit(payload))
      .catch(failed(EXIT_EVENT));
  }

  private dispatchNotification(payload: unknown): void {
    const notification = parseNotification(payload);
    if (notification === null) {
      console.warn("Ignoring unrecognised sidecar notification:", payload);
      return;
    }
    for (const handler of [...this.notificationHandlers]) {
      handler(notification);
    }
  }

  private dispatchExit(payload: unknown): void {
    const code = isRecord(payload) && typeof payload.code === "number" ? payload.code : null;
    for (const handler of [...this.exitHandlers]) {
      handler({ code });
    }
  }
}

/** Validates a notification payload crossing the process boundary. Returns null if unknown. */
export function parseNotification(payload: unknown): SidecarNotification | null {
  return isNotification(payload) ? payload : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringify(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}
