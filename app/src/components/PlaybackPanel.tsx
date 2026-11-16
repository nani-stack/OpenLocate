import { useEffect, useState } from "react";

import { DEMO_ROUTE, DEMO_ROUTE_NAME } from "../demoRoute";
import {
  formatCoordinate,
  formatDistance,
  formatDuration,
  formatProgress,
  formatSpeed,
} from "../format";
import type { RpcClient } from "../rpc/client";
import {
  ROUTE_PROFILES,
  type LatLon,
  type LoadedRoadRoute,
  type PlaybackStatus,
  type RouteProfile,
} from "../rpc/types";
import {
  parseCoordinate,
  resolveSpeedKmh,
  SPEED_PRESETS_KMH,
  type CoordinateErrors,
  type SpeedChoice,
} from "../validation";

interface Props {
  client: RpcClient;
  onError: (context: string, error: unknown) => void;
}

type ControlMethod = "playback.start" | "playback.pause" | "playback.resume" | "playback.stop";

const SPEED_CHOICES: readonly SpeedChoice[] = ["walk", "bike", "drive", "custom"];

const PROFILE_LABELS: Record<RouteProfile, string> = {
  walk: "Walking",
  bike: "Cycling",
  drive: "Driving",
};

function firstError(errors: CoordinateErrors): string {
  return errors.lat ?? errors.lon ?? "Check the coordinates.";
}

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
  const [fromLat, setFromLat] = useState("");
  const [fromLon, setFromLon] = useState("");
  const [toLat, setToLat] = useState("");
  const [toLon, setToLon] = useState("");
  const [profile, setProfile] = useState<RouteProfile>("walk");
  const [fixedSpeed, setFixedSpeed] = useState(false);
  const [roadError, setRoadError] = useState<string | null>(null);
  const [road, setRoad] = useState<(LoadedRoadRoute & { profile: RouteProfile }) | null>(null);

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

  const playing = status?.state === "playing";
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      client.call("playback.status").then(setStatus, () => undefined);
    }, 2000);
    return () => clearInterval(timer);
  }, [client, playing]);

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
      setRoad(null);
      setStatus(await client.call("playback.status"));
    });
  };

  const loadRoad = () => {
    const from = parseCoordinate(fromLat, fromLon);
    const to = parseCoordinate(toLat, toLon);
    if (!from.ok) return setRoadError(`From: ${firstError(from.errors)}`);
    if (!to.ok) return setRoadError(`To: ${firstError(to.errors)}`);
    const speedKmh = fixedSpeed ? currentSpeed() : undefined;
    if (speedKmh === null) return;
    setRoadError(null);
    return act("Load road route", async () => {
      const result = await client.call("playback.loadRoute", {
        waypoints: [
          [from.value.lat, from.value.lon],
          [to.value.lat, to.value.lon],
        ],
        profile,
        ...(speedKmh === undefined ? {} : { speedKmh }),
        loop,
      });
      setLoadedLengthM(result.lengthM);
      setRoad({ ...result, profile });
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
      <h3>Route along roads</h3>
      <div className="row">
        <label>
          From latitude
          <input
            inputMode="decimal"
            value={fromLat}
            onChange={(e) => setFromLat(e.target.value)}
            placeholder="48.858400"
          />
        </label>
        <label>
          From longitude
          <input
            inputMode="decimal"
            value={fromLon}
            onChange={(e) => setFromLon(e.target.value)}
            placeholder="2.294500"
          />
        </label>
      </div>
      <div className="row">
        <label>
          To latitude
          <input
            inputMode="decimal"
            value={toLat}
            onChange={(e) => setToLat(e.target.value)}
            placeholder="48.873800"
          />
        </label>
        <label>
          To longitude
          <input
            inputMode="decimal"
            value={toLon}
            onChange={(e) => setToLon(e.target.value)}
            placeholder="2.295000"
          />
        </label>
      </div>
      <div className="row">
        <label>
          Travel by
          <select value={profile} onChange={(e) => setProfile(e.target.value as RouteProfile)}>
            {ROUTE_PROFILES.map((p) => (
              <option key={p} value={p}>
                {PROFILE_LABELS[p]}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={fixedSpeed}
            onChange={(e) => setFixedSpeed(e.target.checked)}
          />
          Use the speed chosen above
        </label>
        <button type="button" onClick={loadRoad} disabled={busy}>
          Load road route
        </button>
      </div>
      {roadError && <p className="field-error">{roadError}</p>}
      <p className="muted">
        {road
          ? `${PROFILE_LABELS[road.profile]} route loaded: ${formatDistance(road.lengthM)}, ` +
            `about ${formatDuration(road.durationS)} at ${formatSpeed(road.speedKmh)}.`
          : "Without a chosen speed the trip is played at a typical pace for walking, " +
            "cycling or driving on those roads. The start and end are sent to the routing server."}
      </p>
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
