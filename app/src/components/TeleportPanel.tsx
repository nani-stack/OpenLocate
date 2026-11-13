import { useState, type FormEvent } from "react";

import type { RpcClient } from "../rpc/client";
import { parseCoordinate, type CoordinateErrors } from "../validation";

interface Props {
  client: RpcClient;
  onError: (context: string, error: unknown) => void;
}

export function TeleportPanel({ client, onError }: Props) {
  const [latText, setLatText] = useState("");
  const [lonText, setLonText] = useState("");
  const [errors, setErrors] = useState<CoordinateErrors>({});
  const [busy, setBusy] = useState(false);

  async function teleport(event: FormEvent) {
    event.preventDefault();
    const parsed = parseCoordinate(latText, lonText);
    if (!parsed.ok) {
      setErrors(parsed.errors);
      return;
    }
    setErrors({});
    setBusy(true);
    try {
      await client.call("location.set", parsed.value);
    } catch (error) {
      onError("Teleport", error);
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    try {
      await client.call("location.clear");
    } catch (error) {
      onError("Reset to real location", error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Teleport</h2>
      <form onSubmit={teleport} noValidate>
        <label>
          Latitude
          <input
            inputMode="decimal"
            value={latText}
            onChange={(e) => setLatText(e.target.value)}
            placeholder="48.858370"
            aria-invalid={errors.lat !== undefined}
          />
        </label>
        {errors.lat && <p className="field-error">{errors.lat}</p>}
        <label>
          Longitude
          <input
            inputMode="decimal"
            value={lonText}
            onChange={(e) => setLonText(e.target.value)}
            placeholder="2.294481"
            aria-invalid={errors.lon !== undefined}
          />
        </label>
        {errors.lon && <p className="field-error">{errors.lon}</p>}
        <div className="row">
          <button type="submit" disabled={busy}>
            Teleport
          </button>
          <button type="button" onClick={reset} disabled={busy}>
            Reset to real location
          </button>
        </div>
      </form>
    </section>
  );
}
