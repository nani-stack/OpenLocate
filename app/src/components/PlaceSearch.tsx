// One address box. Searches only on Enter or the Search button: the public search service
// forbids searching while the user is still typing.

import { useEffect, useState, type FormEvent } from "react";

import type { RpcClient } from "../rpc/client";
import type { Place } from "../rpc/types";
import { shortPlaceName } from "../trip";

interface Props {
  label: string;
  placeholder: string;
  client: RpcClient;
  chosen: Place | null;
  onChoose: (place: Place | null) => void;
  onError: (context: string, error: unknown) => void;
}

export function PlaceSearch({ label, placeholder, client, chosen, onChoose, onError }: Props) {
  const [text, setText] = useState("");
  const [results, setResults] = useState<Place[] | null>(null);
  const [busy, setBusy] = useState(false);

  // A place can also be chosen from outside (the "My location" button).
  useEffect(() => {
    if (chosen !== null) {
      setText(shortPlaceName(chosen));
      setResults(null);
    }
  }, [chosen]);

  async function search(event: FormEvent) {
    event.preventDefault();
    const query = text.trim();
    if (query === "") return;
    setBusy(true);
    try {
      const found = (await client.call("search.find", { query })).results;
      if (found.length === 1 && found[0] !== undefined) {
        choose(found[0]);
      } else {
        setResults(found);
      }
    } catch (error) {
      onError(`Search for ${label.toLowerCase()}`, error);
    } finally {
      setBusy(false);
    }
  }

  function choose(place: Place) {
    setResults(null);
    setText(shortPlaceName(place));
    onChoose(place);
  }

  function edit(value: string) {
    setText(value);
    setResults(null);
    if (chosen !== null) onChoose(null);
  }

  return (
    <div className="place">
      <form onSubmit={search} className="place-form">
        <label>
          {label}
          <input
            value={text}
            onChange={(e) => edit(e.target.value)}
            placeholder={placeholder}
            maxLength={200}
          />
        </label>
        <button type="submit" disabled={busy || text.trim() === ""}>
          {busy ? "Searching…" : "Search"}
        </button>
      </form>
      {chosen && <p className="place-chosen">✓ {chosen.name}</p>}
      {results !== null && results.length === 0 && (
        <p className="field-error">
          Nothing found. Try adding the city or country, or check the spelling.
        </p>
      )}
      {results !== null && results.length > 0 && (
        <ul className="place-results">
          {results.map((place) => (
            <li key={`${place.lat},${place.lon},${place.name}`}>
              <button type="button" onClick={() => choose(place)}>
                {place.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
