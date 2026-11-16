"""Write THIRD_PARTY_NOTICES.md: every third-party package OpenLocate is built from.

Run it from the repository root with the sidecar's Python, after installing all three parts
(the sidecar's virtualenv, `npm install` in app/, and a Rust toolchain):

    sidecar/.venv/Scripts/python.exe scripts/third_party_notices.py      (Windows)
    sidecar/.venv/bin/python scripts/third_party_notices.py              (macOS, Linux)

It reads what is actually installed or locked, so run it again whenever a dependency changes
and before every release. It lists names, versions and licences; it does not copy licence
texts. A release that ships binaries must also include those texts (see docs/LEGAL.md).
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from importlib import metadata
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "THIRD_PARTY_NOTICES.md"
Row = tuple[str, str, str, str]  # name, version, licence, home page


def _python_licence(meta: metadata.PackageMetadata) -> str:
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [
        c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License")
    ]
    if classifiers:
        return " / ".join(sorted(set(classifiers)))
    text = (meta.get("License") or "").strip()
    return text.splitlines()[0][:60] if text else "not stated"


def _licence_from_file(dist: metadata.Distribution) -> str | None:
    """The first line of a bundled licence file, for packages whose metadata names none."""
    for file in dist.files or []:
        if "licen" in file.name.lower() or "copying" in file.name.lower():
            try:
                text = dist.locate_file(file).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            first = next((line.strip() for line in text.splitlines() if line.strip()), "")
            if first:
                return f"{first[:60]} (from its licence file)"
    return None


def _python_home(meta: metadata.PackageMetadata) -> str:
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in ("homepage", "home", "repository", "source", "source code"):
            return url.strip()
    return meta.get("Home-page") or f"https://pypi.org/project/{meta['Name']}/"


def python_rows() -> list[Row]:
    """Everything the sidecar needs at run time, found by walking its requirements."""
    environment = default_environment()
    seen: dict[str, Row] = {}
    queue = ["openlocate"]
    while queue:
        name = queue.pop()
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        key = dist.metadata["Name"].lower().replace("_", "-")
        if key in seen:
            continue
        licence = _python_licence(dist.metadata)
        if licence == "not stated":
            licence = _licence_from_file(dist) or licence
        seen[key] = (dist.metadata["Name"], dist.version, licence, _python_home(dist.metadata))
        for text in dist.requires or []:
            requirement = Requirement(text)
            marker = requirement.marker
            if marker is None or marker.evaluate({**environment, "extra": ""}):
                queue.append(requirement.name)
    seen.pop("openlocate", None)
    return sorted(seen.values(), key=lambda row: row[0].lower())


def npm_rows() -> list[Row]:
    """Packages that end up in the app (development-only tools are left out)."""
    lock = json.loads((ROOT / "app" / "package-lock.json").read_text(encoding="utf-8"))
    rows: dict[tuple[str, str], Row] = {}
    for path, info in lock["packages"].items():
        if not path or info.get("dev") or info.get("devOptional"):
            continue
        name = path.split("node_modules/")[-1]
        licence = info.get("license") or "not stated"
        rows[(name, info["version"])] = (
            name,
            info["version"],
            licence,
            f"https://www.npmjs.com/package/{name}",
        )
    return sorted(rows.values(), key=lambda row: row[0].lower())


def cargo_rows() -> list[Row]:
    """Every crate Cargo resolves for the app shell, on any platform."""
    result = subprocess.run(
        ["cargo", "metadata", "--format-version", "1"],
        cwd=ROOT / "app" / "src-tauri",
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    data = json.loads(result.stdout)
    ours = set(data["workspace_members"])
    rows = [
        (
            package["name"],
            package["version"],
            package.get("license") or "not stated",
            package.get("repository") or f"https://crates.io/crates/{package['name']}",
        )
        for package in data["packages"]
        if package["id"] not in ours
    ]
    return sorted(set(rows), key=lambda row: row[0].lower())


def _table(rows: list[Row]) -> list[str]:
    lines = ["| Package | Version | Licence |", "|---|---|---|"]
    lines += [
        f"| [{name}]({home}) | {version} | {licence} |" for name, version, licence, home in rows
    ]
    return lines


def _summary(rows: list[Row]) -> str:
    counts = Counter(row[2] for row in rows)
    return ", ".join(f"{licence} ({count})" for licence, count in counts.most_common())


def main() -> int:
    sections = [
        (
            "Sidecar (Python)",
            "Installed in the sidecar's environment and bundled with it.",
            python_rows(),
        ),
        ("App (JavaScript)", "Bundled into the app's user interface.", npm_rows()),
        (
            "App shell (Rust)",
            "Compiled into the app. The list covers every platform, so it is longer than what "
            "any one build contains.",
            cargo_rows(),
        ),
    ]
    lines = [
        "# Third-party notices",
        "",
        "OpenLocate is licensed under GPL-3.0-or-later (see `LICENSE`). It is built from the",
        "third-party software below, each under its own licence. This file is generated by",
        "`scripts/third_party_notices.py`; do not edit it by hand.",
        "",
        "The map data, map tiles, search and routing come from outside services, credited in",
        "`docs/LEGAL.md` and in the app.",
        "",
    ]
    for title, note, rows in sections:
        lines += [
            f"## {title}",
            "",
            note,
            "",
            f"{len(rows)} packages. Licences: {_summary(rows)}.",
            "",
        ]
        lines += _table(rows)
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    unknown = [row[0] for _, _, rows in sections for row in rows if row[2] == "not stated"]
    print(f"wrote {OUT.name}: " + ", ".join(f"{len(rows)} {title}" for title, _, rows in sections))
    if unknown:
        print("no licence stated for: " + ", ".join(unknown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
