// The legal texts shown inside the app. They are the repository's own files, read at build
// time, so the app and the download always carry the same words.

import privacy from "../../PRIVACY.md?raw";
import terms from "../../TERMS.md?raw";
import notices from "../../THIRD_PARTY_NOTICES.md?raw";

export const TERMS_TEXT: string = terms;
export const PRIVACY_TEXT: string = privacy;
export const NOTICES_TEXT: string = notices;

/** Change this when TERMS.md changes in a way people should read again. */
export const TERMS_VERSION = "2026-11-15";

const STORAGE_KEY = "openlocate.termsAccepted";

/** Just enough of `Storage` for the functions below, so tests can pass a plain object. */
export interface KeyValueStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** True once this version of the terms has been accepted on this computer. */
export function termsAccepted(store: KeyValueStore | null): boolean {
  try {
    return store?.getItem(STORAGE_KEY) === TERMS_VERSION;
  } catch {
    return false;
  }
}

export function acceptTerms(store: KeyValueStore | null): void {
  try {
    store?.setItem(STORAGE_KEY, TERMS_VERSION);
  } catch {
    // Storage can be unavailable. The terms are then shown again next time, which is safe.
  }
}

export type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "table"; rows: string[][] };

function plain(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    .replace(/<(https?:[^>]+)>/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1");
}

/** Splits our own simple Markdown into blocks for display. Not a general Markdown parser. */
export function toBlocks(markdown: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: string[] | null = null;
  let table: string[][] | null = null;

  const flush = () => {
    if (paragraph.length > 0) blocks.push({ kind: "paragraph", text: plain(paragraph.join(" ")) });
    if (list !== null) blocks.push({ kind: "list", items: list.map(plain) });
    if (table !== null) blocks.push({ kind: "table", rows: table });
    paragraph = [];
    list = null;
    table = null;
  };

  for (const raw of markdown.split(/\r?\n/)) {
    const line = raw.trimEnd();
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (line.trim() === "") {
      flush();
    } else if (heading) {
      flush();
      blocks.push({ kind: "heading", level: (heading[1] ?? "#").length, text: plain(heading[2] ?? "") });
    } else if (line.startsWith("|")) {
      if (table === null) {
        flush();
        table = [];
      }
      const cells = line.split("|").slice(1, -1).map((cell) => plain(cell.trim()));
      if (!cells.every((cell) => /^:?-+:?$/.test(cell))) table.push(cells);
    } else if (/^\s*(?:[-*]|\d+\.)\s+/.test(line)) {
      if (list === null) {
        flush();
        list = [];
      }
      list.push(line.replace(/^\s*(?:[-*]|\d+\.)\s+/, ""));
    } else if (list !== null && /^\s+\S/.test(raw)) {
      list[list.length - 1] += ` ${line.trim()}`;
    } else {
      if (list !== null || table !== null) flush();
      paragraph.push(line.trim());
    }
  }
  flush();
  return blocks;
}
