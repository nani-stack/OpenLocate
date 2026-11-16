// The main screen: pick a start and an end by address, get a route along real roads, and
// travel it in real time on the connected device.

import { useCallback, useEffect, useMemo, useState } from "react";

import { formatDistance, formatDuration, formatProgress, formatSpeed } from "../format";
import type { RpcClient } from "../rpc/client";
import {
  ROUTE_PROFILES,
  type LatLon,
  type LoadedRoadRoute,
  type Place,
  type PlaybackStatus,
  type RouteProfile,
} from "../rpc/types";
import { PROFILE_LABELS, remainingSeconds, sameRequest, type RouteRequest } from "../trip";
import { DeviceBar } from "./DeviceBar";
import { MapView } from "./MapView";
import { PlaceSearch } from "./PlaceSearch";

interface Props {
  client: RpcClient;
  onError: (context: string, error: unknown) => void;
  /** False while another tab is showing. The device may have been changed there. */
  active: boolean;
}

interface LoadedTrip {
  request: RouteRequest;
  route: LoadedRoadRoute;
}

const STATUS_POLL_MS = 2000;

function point(place: Place): LatLon {
  return { lat: place.lat, lon: place.lon };
}

export function TripScreen({ client, onError, active }: Props) {
  const [from, setFrom] = useState<Place | null>(null);
  const [to, setTo] = useState<Place | null>(null);
  const [profile, setProfile] = useState<RouteProfile>("walk");
  const [trip, setTrip] = useState<LoadedTrip | null>(null);
  const [status, setStatus] = useState<PlaybackStatus | null>(null);
  const [position, setPosition] = useState<LatLon | null>(null);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [home, setHome] = useState<LatLon | null>(null);
  const [homeNote, setHomeNote] = useState<string | null>(null);

  // Ask the computer where it is. The answer stays in the app unless it is used as the start
  // of a route. The first try can fail while the system is still finding a position, so the
  // "Start from my location" button asks again.
  const locate = useCallback((useAsStart: boolean) => {
    if (!("geolocation" in navigator)) {
      setHomeNote("This computer cannot report its location, so search for a start.");
      return;
    }
    setHomeNote(null);
    navigator.geolocation.getCurrentPosition(
      (found) => {
        const here = { lat: found.coords.latitude, lon: found.coords.longitude };
        setHome(here);
        if (useAsStart) setFrom({ name: "My location", ...here });
      },
      (error) =>
        setHomeNote(
          error.code === error.PERMISSION_DENIED
            ? "This app is not allowed to read this computer's location, so search for a start."
            : error.code === error.TIMEOUT
              ? "This computer's location took too long to find. Try again, or search for a start."
              : "This computer's location could not be found. Try again, or search for a start.",
        ),
      { enableHighAccuracy: false, timeout: 15_000, maximumAge: 600_000 },
    );
  }, []);

  useEffect(() => locate(false), [locate]);

  useEffect(
    () =>
      client.onNotification((notification) => {
        if (notification.method === "location.updated") {
          setPosition({ lat: notification.params.lat, lon: notification.params.lon });
        } else if (notification.method === "playback.state") {
          setStatus(notification.params);
        } else {
          onError("Travel", notification.params);
        }
      }),
    [client, onError],
  );

  const playing = status?.state === "playing";
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      client.call("playback.status").then(setStatus, () => undefined);
    }, STATUS_POLL_MS);
    return () => clearInterval(timer);
  }, [client, playing]);

  const wanted: RouteRequest | null = useMemo(
    () => (from && to ? { from: point(from), to: point(to), profile } : null),
    [from, to, profile],
  );
  const current = trip !== null && sameRequest(trip.request, wanted);

  const act = useCallback(
    async (context: string, action: () => Promise<void>) => {
      setBusy(true);
      setNote(null);
      try {
        await action();
      } catch (error) {
        onError(context, error);
      } finally {
        setBusy(false);
      }
    },
    [onError],
  );

  const getRoute = () => {
    if (wanted === null) return;
    return act("Get route", async () => {
      const route = await client.call("playback.loadRoute", {
        waypoints: [
          [wanted.from.lat, wanted.from.lon],
          [wanted.to.lat, wanted.to.lon],
        ],
        profile: wanted.profile,
      });
      setTrip({ request: wanted, route });
      setStatus(await client.call("playback.status"));
    });
  };

  const control = (
    method: "playback.start" | "playback.pause" | "playback.resume" | "playback.stop",
    label: string,
  ) => act(label, async () => setStatus(await client.call(method)));

  const teleport = (place: Place) =>
    act("Teleport", async () => {
      await client.call("location.set", point(place));
      setStatus(await client.call("playback.status"));
    });

  const reset = () =>
    act("Reset to real location", async () => {
      await client.call("location.clear");
      setPosition(null);
      setStatus(await client.call("playback.status"));
      setNote(
        "The device has stopped faking its location. It can keep showing the old place for a " +
          "few minutes. If it does, turn its Wi-Fi off and on, or restart it.",
      );
    });

  const state = status?.state ?? "idle";
  const canTravel = current && connected;

  return (
    <div className="trip">
      <aside className="trip-side">
        <DeviceBar client={client} onError={onError} onConnected={setConnected} active={active} />

        <section className="card">
          <h2>Trip</h2>
          <PlaceSearch
            label="From"
            placeholder="Address or place, then Enter"
            client={client}
            chosen={from}
            onChoose={setFrom}
            onError={onError}
          />
          <button
            type="button"
            className="link"
            onClick={() =>
              home ? setFrom({ name: "My location", lat: home.lat, lon: home.lon }) : locate(true)
            }
          >
            Start from my location
          </button>
          {home === null && homeNote && <p className="muted small">{homeNote}</p>}
          <PlaceSearch
            label="To"
            placeholder="Address or place, then Enter"
            client={client}
            chosen={to}
            onChoose={setTo}
            onError={onError}
          />
          <div className="modes" role="group" aria-label="Travel by">
            {ROUTE_PROFILES.map((p) => (
              <button
                key={p}
                type="button"
                className={p === profile ? "mode mode-on" : "mode"}
                aria-pressed={p === profile}
                onClick={() => setProfile(p)}
              >
                {PROFILE_LABELS[p]}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="primary"
            onClick={getRoute}
            disabled={busy || wanted === null}
          >
            {trip !== null && !current ? "Update route" : "Get route"}
          </button>
          {wanted === null && (
            <p className="muted">Search for a start and an end to get a route.</p>
          )}
          {trip !== null && !current && wanted !== null && (
            <p className="muted">The start, end or way of travelling changed. Update the route.</p>
          )}
        </section>

        {trip !== null && current && (
          <section className="card">
            <h2>{PROFILE_LABELS[trip.request.profile]} route</h2>
            <p className="summary">
              <strong>{formatDistance(trip.route.lengthM)}</strong> · about{" "}
              <strong>{formatDuration(trip.route.durationS)}</strong> at{" "}
              {formatSpeed(trip.route.speedKmh)}
            </p>
            <div className="row">
              {state === "playing" ? (
                <button type="button" onClick={() => control("playback.pause", "Pause")}>
                  Pause
                </button>
              ) : state === "paused" ? (
                <button
                  type="button"
                  className="primary"
                  onClick={() => control("playback.resume", "Resume")}
                  disabled={busy}
                >
                  Resume
                </button>
              ) : (
                <button
                  type="button"
                  className="primary"
                  onClick={() => control("playback.start", "Start")}
                  disabled={busy || !canTravel}
                >
                  {state === "finished" ? "Travel again" : "Start"}
                </button>
              )}
              <button
                type="button"
                onClick={() => control("playback.stop", "Stop")}
                disabled={busy || state === "idle"}
              >
                Stop
              </button>
            </div>
            {!connected && <p className="muted">Connect a device above to start.</p>}
            {status !== null && state !== "idle" && (
              <>
                <progress value={status.progress} max={1} />
                <p className="muted">
                  {state === "finished"
                    ? "Arrived. The device stays at the destination."
                    : `${formatProgress(status.progress)} · ${formatDistance(status.distanceM)} of ` +
                      `${formatDistance(status.lengthM)} · about ` +
                      `${formatDuration(remainingSeconds(trip.route.durationS, status.progress))} left`}
                </p>
              </>
            )}
          </section>
        )}

        <section className="card">
          <h2>Location</h2>
          <div className="row">
            <button
              type="button"
              onClick={() => to && teleport(to)}
              disabled={busy || to === null || !connected}
            >
              Jump to the destination
            </button>
            <button type="button" onClick={reset} disabled={busy || !connected}>
              Reset to real location
            </button>
          </div>
          {note && <p className="muted">{note}</p>}
          <p className="muted small">
            The cable must stay plugged in while a location is faked. Closing the app ends it.
          </p>
        </section>

        <p className="muted small">
          Search by Nominatim, routes by OSRM (FOSSGIS), map by OpenFreeMap. Data ©
          OpenStreetMap contributors; report a map error at openstreetmap.org/fixthemap. Your
          searches and route ends are sent to those services.
        </p>
        <p className="muted small">
          OpenLocate is free software under the GNU GPL version 3 or later and comes with no
          warranty. Use it only with your own device; other apps may forbid a faked location.
          Not affiliated with Apple. See TERMS.md and PRIVACY.md.
        </p>
      </aside>
      <MapView
        from={from && point(from)}
        to={to && point(to)}
        path={trip !== null && current ? trip.route.path : null}
        position={position}
        follow={playing}
        home={home}
      />
    </div>
  );
}
