import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { RpcClient } from "./rpc/client";
import { tauriTransport } from "./rpc/tauriTransport";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("index.html is missing the #root element.");
}

const client = new RpcClient(tauriTransport);

createRoot(container).render(
  <StrictMode>
    <App client={client} />
  </StrictMode>,
);
