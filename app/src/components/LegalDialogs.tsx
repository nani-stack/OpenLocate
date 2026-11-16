// The first-run terms screen and the About and legal screen.

import { useMemo, useState } from "react";

import { NOTICES_TEXT, PRIVACY_TEXT, TERMS_TEXT, toBlocks, type Block } from "../legal";

function Document({ text }: { text: string }) {
  const blocks = useMemo(() => toBlocks(text), [text]);
  return (
    <div className="doc">
      {blocks.map((block: Block, index) => {
        switch (block.kind) {
          case "heading":
            return block.level <= 1 ? (
              <h3 key={index}>{block.text}</h3>
            ) : (
              <h4 key={index}>{block.text}</h4>
            );
          case "paragraph":
            return <p key={index}>{block.text}</p>;
          case "list":
            return (
              <ul key={index}>
                {block.items.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            );
          case "table":
            return (
              <table key={index}>
                <tbody>
                  {block.rows.map((row, r) => (
                    <tr key={r}>
                      {row.map((cell, c) => (r === 0 ? <th key={c}>{cell}</th> : <td key={c}>{cell}</td>))}
                    </tr>
                  ))}
                </tbody>
              </table>
            );
        }
      })}
    </div>
  );
}

interface FirstRunProps {
  onAccept: () => void;
}

/** Shown before anything else until the terms have been accepted once. */
export function FirstRun({ onAccept }: FirstRunProps) {
  return (
    <div className="overlay">
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="first-run-title">
        <h2 id="first-run-title">Before you start</h2>
        <ul className="points">
          <li>
            OpenLocate makes your iPhone or iPad report a location you choose. Use it only with
            a device that is yours.
          </li>
          <li>
            Many apps and games forbid a faked location and can suspend or ban your account.
            That risk is yours.
          </li>
          <li>
            Do not use it to deceive or harm anyone, or to get round a rule or law that applies
            to you.
          </li>
          <li>
            Address searches, routes and map views are sent to free outside services. Nothing
            is sent to the people who make OpenLocate.
          </li>
          <li>It is free software and comes with no warranty.</li>
        </ul>
        <p className="muted small">The full terms:</p>
        <div className="dialog-scroll">
          <Document text={TERMS_TEXT} />
        </div>
        <div className="dialog-actions">
          <button type="button" className="primary" onClick={onAccept}>
            I understand and agree
          </button>
        </div>
        <p className="muted small">If you do not agree, close OpenLocate.</p>
      </div>
    </div>
  );
}

type Tab = "terms" | "privacy" | "licences";

const TABS: readonly { id: Tab; label: string; text: string }[] = [
  { id: "terms", label: "Terms", text: TERMS_TEXT },
  { id: "privacy", label: "Privacy", text: PRIVACY_TEXT },
  { id: "licences", label: "Open-source licences", text: NOTICES_TEXT },
];

interface AboutProps {
  version: string | null;
  onClose: () => void;
}

export function AboutDialog({ version, onClose }: AboutProps) {
  const [tab, setTab] = useState<Tab>("terms");
  const current = TABS.find((entry) => entry.id === tab) ?? TABS[0];
  return (
    <div className="overlay">
      <div className="dialog dialog-wide" role="dialog" aria-modal="true" aria-labelledby="about-title">
        <div className="card-head">
          <h2 id="about-title">About OpenLocate</h2>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="muted small">
          Version {version ?? "unknown"}. Free software under the GNU General Public License,
          version 3 or later, with no warranty. Not affiliated with Apple. The licence text and
          the licences of the software it is built from are in the "legal" folder next to the
          app.
        </p>
        <div className="tabs">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={entry.id === tab ? "tab tab-on" : "tab"}
              aria-pressed={entry.id === tab}
              onClick={() => setTab(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>
        <div className="dialog-scroll dialog-scroll-tall">
          {current && <Document text={current.text} />}
        </div>
      </div>
    </div>
  );
}
