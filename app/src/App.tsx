import { useCallback, useEffect, useRef, useState } from "react";

import { DevicePanel } from "./components/DevicePanel";
import { ErrorBanner, type ReportedError } from "./components/ErrorBanner";
import { Header, type SidecarStatus } from "./components/Header";
import { PlaybackPanel } from "./components/PlaybackPanel";
import { TeleportPanel } from "./components/TeleportPanel";
import { toRpcError, type RpcClient } from "./rpc/client";
import type { AppInfo } from "./rpc/types";

interface Props {
  client: RpcClient;
}

export function App({ client }: Props) {
  const [status, setStatus] = useState<SidecarStatus>({ kind: "starting" });
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [errors, setErrors] = useState<ReportedError[]>([]);
  const [restarting, setRestarting] = useState(false);
  const nextErrorId = useRef(1);

  const reportError = useCallback((context: string, error: unknown) => {
    const id = nextErrorId.current++;
    setErrors((current) => [...current, { id, context, error: toRpcError(error).toData() }]);
  }, []);

  const dismissError = useCallback((id: number) => {
    setErrors((current) => current.filter((e) => e.id !== id));
  }, []);

  const loadInfo = useCallback(async () => {
    try {
      setInfo(await client.call("app.info"));
      setStatus({ kind: "running" });
    } catch (error) {
      setStatus({ kind: "exited", code: null });
      reportError("Contact the sidecar", error);
    }
  }, [client, reportError]);

  useEffect(() => {
    void loadInfo();
    return client.onExit(({ code }) => setStatus({ kind: "exited", code }));
  }, [client, loadInfo]);

  const restart = useCallback(async () => {
    setRestarting(true);
    setStatus({ kind: "starting" });
    try {
      await client.restart();
      await loadInfo();
    } catch (error) {
      setStatus({ kind: "exited", code: null });
      reportError("Restart sidecar", error);
    } finally {
      setRestarting(false);
    }
  }, [client, loadInfo, reportError]);

  return (
    <div className="app">
      <Header status={status} info={info} restarting={restarting} onRestart={restart} />
      <ErrorBanner errors={errors} onDismiss={dismissError} />
      <main className="panels">
        <DevicePanel client={client} onError={reportError} />
        <TeleportPanel client={client} onError={reportError} />
        <PlaybackPanel client={client} onError={reportError} />
      </main>
    </div>
  );
}
