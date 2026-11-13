import { useState } from "react";

import type { RpcClient } from "../rpc/client";
import type { DeviceInfo } from "../rpc/types";

interface Props {
  client: RpcClient;
  onError: (context: string, error: unknown) => void;
}

export function DevicePanel({ client, onError }: Props) {
  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [busy, setBusy] = useState(false);

  async function act(context: string, action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      onError(context, error);
    } finally {
      setBusy(false);
    }
  }

  const refresh = () =>
    act("Refresh devices", async () => {
      const { devices: found } = await client.call("device.list");
      setDevices(found);
    });

  const connect = (id: string) =>
    act("Connect", async () => {
      const info = await client.call("device.connect", { id });
      setDevices((current) => current.map((d) => (d.id === info.id ? info : d)));
    });

  const disconnect = () =>
    act("Disconnect", async () => {
      await client.call("device.disconnect");
      const { devices: found } = await client.call("device.list");
      setDevices(found);
    });

  return (
    <section className="panel">
      <h2>Device</h2>
      <button type="button" onClick={refresh} disabled={busy}>
        Refresh
      </button>
      {devices.length === 0 ? (
        <p className="muted">No devices listed. Press Refresh.</p>
      ) : (
        <ul className="devices">
          {devices.map((device) => (
            <li key={device.id}>
              <div>
                <strong>{device.name}</strong> <span className="muted">{device.model}</span>
                <br />
                <small>
                  iOS {device.osVersion} · {device.connection} · {device.state}
                </small>
              </div>
              {device.state === "ready" ? (
                <button type="button" onClick={disconnect} disabled={busy}>
                  Disconnect
                </button>
              ) : (
                <button type="button" onClick={() => connect(device.id)} disabled={busy}>
                  Connect
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
