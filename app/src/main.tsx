import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { RpcClient, type Transport } from "./rpc/client";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("index.html is missing the #root element.");
}

// Inside the app, talk to the real sidecar through Tauri. In a plain browser (`npm run dev`
// without Tauri) there is no sidecar, so a made-up one keeps the screens usable.
async function loadTransport(): Promise<Transport> {
  if ("__TAURI_INTERNALS__" in window) {
    return (await import("./rpc/tauriTransport")).tauriTransport;
  }
  return (await import("./dev/demoTransport")).createDemoTransport();
}

const root = createRoot(container);
void loadTransport().then((transport) => {
  root.render(
    <StrictMode>
      <App client={new RpcClient(transport)} />
    </StrictMode>,
  );
});
