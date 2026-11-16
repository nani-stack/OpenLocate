import type { AppInfo } from "../rpc/types";

export type SidecarStatus =
  | { kind: "starting" }
  | { kind: "running" }
  | { kind: "exited"; code: number | null };

interface Props {
  status: SidecarStatus;
  info: AppInfo | null;
  restarting: boolean;
  onRestart: () => void;
}

function describeStatus(status: SidecarStatus): string {
  switch (status.kind) {
    case "starting":
      return "starting…";
    case "running":
      return "running";
    case "exited":
      return status.code === null ? "exited" : `exited (code ${status.code})`;
  }
}

export function Header({ status, info, restarting, onRestart }: Props) {
  return (
    <header className="header">
      <dl className="facts">
        <dt>Sidecar</dt>
        <dd className={`status status-${status.kind}`}>
          {describeStatus(status)}{" "}
          <button type="button" onClick={onRestart} disabled={restarting}>
            {restarting ? "Restarting…" : "Restart"}
          </button>
        </dd>
        <dt>Backend</dt>
        <dd>{info?.backend ?? "unknown"}</dd>
        <dt>Version</dt>
        <dd>{info?.version ?? "unknown"}</dd>
        <dt>Log file</dt>
        <dd className="mono">{info?.logFile ?? "unknown"}</dd>
      </dl>
    </header>
  );
}
