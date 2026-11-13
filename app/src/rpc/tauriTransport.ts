// The real transport: Tauri's IPC. Kept apart from client.ts so tests never load Tauri.

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

import type { Transport } from "./client";

export const tauriTransport: Transport = {
  invoke: (command, args) => invoke(command, args),
  listen: (event, handler) => listen(event, (e) => handler(e.payload)),
};
