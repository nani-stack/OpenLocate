// The device line of the map screen: find the iPhone or iPad and connect to it.

import { useCallback, useEffect, useState } from "react";

import type { RpcClient } from "../rpc/client";
import type { DeviceInfo, DeviceState } from "../rpc/types";

interface Props {
  client: RpcClient;
  onError: (context: string, error: unknown) => void;
  onConnected: (connected: boolean) => void;
  /** Look again whenever this turns true: the device may have changed on another tab. */
  active: boolean;
}

const STATE_HELP: Partial<Record<DeviceState, string>> = {
  needs_trust: "Unlock it and tap Trust, then press Connect.",
  needs_developer_mode: "Turn on Developer Mode on it, then press Connect.",
  error: "It could not be read. Unlock it and press Find devices.",
};

export function DeviceBar({ client, onError, onConnected, active }: Props) {
  const [devices, setDevices] = useState<DeviceInfo[] | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const found = (await client.call("device.list")).devices;
      setDevices(found);
      onConnected(found.some((d) => d.state === "ready"));
    } catch (error) {
      onError("Find devices", error);
    } finally {
      setBusy(false);
    }
  }, [client, onConnected, onError]);

  useEffect(() => {
    if (active) void refresh();
  }, [refresh, active]);

  async function connect(id: string) {
    setBusy(true);
    try {
      const info = await client.call("device.connect", { id });
      setDevices((current) => (current ?? []).map((d) => (d.id === info.id ? info : d)));
      onConnected(info.state === "ready");
    } catch (error) {
      onError("Connect", error);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await client.call("device.disconnect");
      onConnected(false);
    } catch (error) {
      onError("Disconnect", error);
    } finally {
      setBusy(false);
    }
    await refresh();
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>Device</h2>
        <button type="button" onClick={() => void refresh()} disabled={busy}>
          Find devices
        </button>
      </div>
      {devices === null ? (
        <p className="muted">Looking for devices…</p>
      ) : devices.length === 0 ? (
        <p className="muted">
          No iPhone or iPad found. Plug it in with a USB cable, unlock it, then press Find
          devices.
        </p>
      ) : (
        <ul className="devices">
          {devices.map((device) => (
            <li key={device.id}>
              <div>
                <strong>{device.name}</strong>
                <br />
                <small className="muted">
                  {device.model} · iOS {device.osVersion} ·{" "}
                  {device.state === "ready" ? "connected" : "not connected"}
                </small>
                {STATE_HELP[device.state] && (
                  <small className="field-error"> {STATE_HELP[device.state]}</small>
                )}
              </div>
              {device.state === "ready" ? (
                <button type="button" onClick={() => void disconnect()} disabled={busy}>
                  Disconnect
                </button>
              ) : (
                <button type="button" onClick={() => void connect(device.id)} disabled={busy}>
                  {busy ? "Working…" : "Connect"}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
