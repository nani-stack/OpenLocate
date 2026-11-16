import { useCallback, useEffect, useRef, useState } from "react";

import { DevicePanel } from "./components/DevicePanel";
import { ErrorBanner, type ReportedError } from "./components/ErrorBanner";
import { Header, type SidecarStatus } from "./components/Header";
import { AboutDialog, FirstRun } from "./components/LegalDialogs";
import { PlaybackPanel } from "./components/PlaybackPanel";
import { TeleportPanel } from "./components/TeleportPanel";
import { TripScreen } from "./components/TripScreen";
import { acceptTerms, termsAccepted } from "./legal";
import { toRpcError, type RpcClient } from "./rpc/client";
import type { AppInfo } from "./rpc/types";

interface Props {
  client: RpcClient;
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function App({ client }: Props) {
  const [status, setStatus] = useState<SidecarStatus>({ kind: "starting" });
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [errors, setErrors] = useState<ReportedError[]>([]);
  const [restarting, setRestarting] = useState(false);
  const [view, setView] = useState<"trip" | "console">("trip");
  const [accepted, setAccepted] = useState(() => termsAccepted(storage()));
  const [aboutOpen, setAboutOpen] = useState(false);
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

  // While a dialog is open, the screens behind it cannot be clicked, tabbed to or read out.
  const blocked = !accepted || aboutOpen;

  const tab = (name: "trip" | "console", label: string) => (
    <button
      type="button"
      className={view === name ? "tab tab-on" : "tab"}
      aria-pressed={view === name}
      onClick={() => setView(name)}
    >
      {label}
    </button>
  );

  return (
    <div className={view === "trip" ? "app app-trip" : "app"}>
      <nav className="topbar">
        <h1>OpenLocate</h1>
        <div className="tabs">
          {tab("trip", "Map")}
          {tab("console", "Developer console")}
        </div>
        <button type="button" className="topbar-end" onClick={() => setAboutOpen(true)}>
          About and legal
        </button>
        {status.kind !== "running" && (
          <span className={`status status-${status.kind}`}>
            {status.kind === "starting" ? "Starting…" : "The helper program stopped."}{" "}
            {status.kind === "exited" && (
              <button type="button" onClick={restart} disabled={restarting}>
                {restarting ? "Restarting…" : "Restart it"}
              </button>
            )}
          </span>
        )}
      </nav>
      <ErrorBanner errors={errors} onDismiss={dismissError} />
      {!accepted && (
        <FirstRun
          onAccept={() => {
            acceptTerms(storage());
            setAccepted(true);
          }}
        />
      )}
      {aboutOpen && <AboutDialog version={info?.version ?? null} onClose={() => setAboutOpen(false)} />}
      {/* Both screens stay mounted: the trip being planned must survive a look at the console. */}
      <div className="screen" hidden={view !== "trip"} inert={blocked}>
        <TripScreen client={client} onError={reportError} active={view === "trip"} />
      </div>
      <div className="screen screen-console" hidden={view !== "console"} inert={blocked}>
        <Header status={status} info={info} restarting={restarting} onRestart={restart} />
        <main className="panels">
          <DevicePanel client={client} onError={reportError} />
          <TeleportPanel client={client} onError={reportError} />
          <PlaybackPanel client={client} onError={reportError} />
        </main>
      </div>
    </div>
  );
}
