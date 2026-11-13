import { useEffect, useState } from "react";

import { DEMO_ROUTE, DEMO_ROUTE_NAME } from "../demoRoute";
import {
  formatCoordinate,
  formatDistance,
  formatProgress,
  formatSpeed,
} from "../format";
import type { RpcClient } from "../rpc/client";
import type { LatLon, PlaybackStatus } from "../rpc/types";
import { resolveSpeedKmh, SPEED_PRESETS_KMH, type SpeedChoice } from "../validation";

interface Props {
  client: RpcClient;
  onError: (context: string, error: unknown) => void;
}

type ControlMethod = "playback.start" | "playback.pause" | "playback.resume" | "playback.stop";

const SPEED_CHOICES: readonly SpeedChoice[] = ["walk", "bike", "drive", "custom"];

function choiceLabel(choice: SpeedChoice): string {
  return choice === "custom" ? "custom" : `${choice} (${SPEED_PRESETS_KMH[choice]} km/h)`;
}

export function PlaybackPanel({ client, onError }: Props) {
  const [choice, setChoice] = useState<SpeedChoice>("walk");
  const [customText, setCustomText] = useState("");
  const [loop, setLoop] = useState(false);
  const [speedError, setSpeedError] = useState<string | null>(null);
  const [loadedLengthM, setLoadedLengthM] = useState<number | null>(null);
  const [status, setStatus] = useState<PlaybackStatus | null>(null);
  const [position, setPosition] = useState<LatLon | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(
    () =>
      client.onNotification((notification) => {
        if (notification.method === "playback.state") {
          setStatus(notification.params);
          if (notification.params.position) setPosition(notification.params.position);
        } else if (
          notification.method === "location.updated" &&
          notification.params.source === "playback"
        ) {
          setPosition({ lat: notification.params.lat, lon: notification.params.lon });
        } else if (notification.method === "playback.error") {
          onError("Playback", notification.params);
        }
      }),
    [client, onError],
  );

  function currentSpeed(): number | null {
    const speed = resolveSpeedKmh(choice, customText);
    if (!speed.ok) {
      setSpeedError(speed.error);
      return null;
    }
    setSpeedError(null);
    return speed.value;
  }

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

  const loadDemo = () => {
    const speedKmh = currentSpeed();
    if (speedKmh === null) return;
    return act("Load demo route", async () => {
      const result = await client.call("playback.load", {
        points: DEMO_ROUTE.map(([lat, lon]) => [lat, lon]),
        speedKmh,
        loop,
      });
      setLoadedLengthM(result.lengthM);
      setStatus(await client.call("playback.status"));
    });
  };

  const setSpeed = () => {
    const speedKmh = currentSpeed();
    if (speedKmh === null) return;
    return act("Set speed", async () => {
      setStatus(await client.call("playback.setSpeed", { speedKmh }));
    });
  };

  const control = (method: ControlMethod, label: string) =>
    act(label, async () => {
      setStatus(await client.call(method));
    });

  const state = status?.state;

  return (
    <section className="panel">
      <h2>Playback</h2>
      <p className="muted">Demo route: {DEMO_ROUTE_NAME}</p>
      <div className="row">
        <label>
          Speed
          <select value={choice} onChange={(e) => setChoice(e.target.value as SpeedChoice)}>
            {SPEED_CHOICES.map((c) => (
              <option key={c} value={c}>
                {choiceLabel(c)}
              </option>
            ))}
          </select>
        </label>
        {choice === "custom" && (
          <label>
            km/h
            <input
              inputMode="decimal"
              value={customText}
              onChange={(e) => setCustomText(e.target.value)}
              placeholder="30"
              aria-invalid={speedError !== null}
            />
          </label>
        )}
        <label className="checkbox">
          <input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} />
          Loop
        </label>
      </div>
      {speedError && <p className="field-error">{speedError}</p>}
      <div className="row">
        <button type="button" onClick={loadDemo} disabled={busy}>
          Load demo route
        </button>
        <button type="button" onClick={setSpeed} disabled={busy || loadedLengthM === null}>
          Set speed
        </button>
      </div>
      <p className="muted">Loop takes effect the next time the route is loaded.</p>
      <div className="row">
        <button type="button" onClick={() => control("playback.start", "Start")} disabled={busy}>
          Start
        </button>
        <button
          type="button"
          onClick={() => control("playback.pause", "Pause")}
          disabled={busy || state !== "playing"}
        >
          Pause
        </button>
        <button
          type="button"
          onClick={() => control("playback.resume", "Resume")}
          disabled={busy || state !== "paused"}
        >
          Resume
        </button>
        <button type="button" onClick={() => control("playback.stop", "Stop")} disabled={busy}>
          Stop
        </button>
      </div>
      <dl className="readout">
        <dt>State</dt>
        <dd>{state ?? "no route loaded"}</dd>
        <dt>Progress</dt>
        <dd>{status ? formatProgress(status.progress) : "–"}</dd>
        <dt>Distance</dt>
        <dd>
          {status
            ? `${formatDistance(status.distanceM)} of ${formatDistance(status.lengthM)}`
            : "–"}
        </dd>
        <dt>Speed</dt>
        <dd>{status ? formatSpeed(status.speedKmh) : "–"}</dd>
        <dt>Lap</dt>
        <dd>{status ? status.lap : "–"}</dd>
        <dt>Position</dt>
        <dd className="mono">
          {position
            ? `${formatCoordinate(position.lat)}, ${formatCoordinate(position.lon)}`
            : "–"}
        </dd>
      </dl>
    </section>
  );
}
