import { describe, expect, it, vi } from "vitest";

vi.mock("../../TERMS.md?raw", () => ({ default: "# Terms" }));
vi.mock("../../PRIVACY.md?raw", () => ({ default: "# Privacy" }));
vi.mock("../../THIRD_PARTY_NOTICES.md?raw", () => ({ default: "# Notices" }));

import { acceptTerms, termsAccepted, TERMS_VERSION, toBlocks, type KeyValueStore } from "./legal";

function memoryStore(): KeyValueStore & { values: Map<string, string> } {
  const values = new Map<string, string>();
  return {
    values,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => void values.set(key, value),
  };
}

describe("accepting the terms", () => {
  it("is remembered for this version only", () => {
    const store = memoryStore();
    expect(termsAccepted(store)).toBe(false);
    acceptTerms(store);
    expect(termsAccepted(store)).toBe(true);
    expect([...store.values.values()]).toEqual([TERMS_VERSION]);
    store.values.set([...store.values.keys()][0] ?? "", "2020-01-01");
    expect(termsAccepted(store)).toBe(false);
  });

  it("asks again when storage is missing or broken", () => {
    expect(termsAccepted(null)).toBe(false);
    const broken: KeyValueStore = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(termsAccepted(broken)).toBe(false);
    expect(() => acceptTerms(broken)).not.toThrow();
  });
});

describe("showing our Markdown", () => {
  it("splits headings, paragraphs, lists and tables", () => {
    const blocks = toBlocks(
      [
        "# Title",
        "",
        "First line of a",
        "paragraph with `code` and **bold**.",
        "",
        "- one [link](https://example.org)",
        "  continued",
        "- two",
        "",
        "| When | Sent to |",
        "|---|---|",
        "| Now | <https://example.org> |",
        "",
        "## Next",
        "1. numbered",
      ].join("\n"),
    );
    expect(blocks).toEqual([
      { kind: "heading", level: 1, text: "Title" },
      { kind: "paragraph", text: "First line of a paragraph with code and bold." },
      { kind: "list", items: ["one link continued", "two"] },
      {
        kind: "table",
        rows: [
          ["When", "Sent to"],
          ["Now", "https://example.org"],
        ],
      },
      { kind: "heading", level: 2, text: "Next" },
      { kind: "list", items: ["numbered"] },
    ]);
  });
});
