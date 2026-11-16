"""Write the licence texts of every third-party package into one file for the installer.

    sidecar/.venv/Scripts/python.exe scripts/third_party_licenses.py      (Windows)

Most open-source licences require their text and copyright lines to travel with the program.
THIRD_PARTY_NOTICES.md only lists names; this collects the actual files into
app/src-tauri/legal-texts/THIRD_PARTY_LICENSES.txt, which the installer ships. The output is
not committed: it is rebuilt from what is installed each time an installer is made.

Some packages ship no licence file and only name their licence. For those the file says so
and points to the standard text of that licence, which is included once at the end.
"""

from __future__ import annotations

import json
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import third_party_notices as notices

ROOT = notices.ROOT
OUT = ROOT / "app" / "src-tauri" / "legal-texts" / "THIRD_PARTY_LICENSES.txt"
NAMES = ("licen", "copying", "notice", "unlicense", "copyright")
MAX_FILE_BYTES = 400_000

POINTER = "(This package ships no licence file. See the standard licence texts at the end.)"

MIT = """Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."""

BSD3 = """Redistribution and use in source and binary forms, with or without modification, are
permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of
   conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice, this list of
   conditions and the following disclaimer in the documentation and/or other materials
   provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors may be used to
   endorse or promote products derived from this software without specific prior written
   permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE."""

# Long standard licences are copied from a package that does ship the text. Each entry is
# the heading to print and the words the text must start with.
COPIED_STANDARD = [
    ("Apache License, Version 2.0", "Apache License"),
    ("Mozilla Public License, Version 2.0", "Mozilla Public License Version 2.0"),
]


def _is_licence(path: Path) -> bool:
    name = path.name.lower()
    return any(part in name for part in NAMES) and path.suffix.lower() not in (
        ".py",
        ".pyc",
        ".rs",
        ".js",
    )


def _read(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _from_folder(folder: Path) -> list[tuple[str, str]]:
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and _is_licence(path):
            text = _read(path)
            if text:
                found.append((path.name, text))
    return found


def python_texts(name: str) -> list[tuple[str, str]]:
    dist = metadata.distribution(name)
    found = []
    for file in dist.files or []:
        located = Path(str(dist.locate_file(file)))
        if _is_licence(located):
            text = _read(located)
            if text:
                found.append((located.name, text))
    return found


def cargo_folders() -> dict[tuple[str, str], Path]:
    result = subprocess.run(
        ["cargo", "metadata", "--format-version", "1"],
        cwd=ROOT / "app" / "src-tauri",
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    data = json.loads(result.stdout)
    return {(p["name"], p["version"]): Path(p["manifest_path"]).parent for p in data["packages"]}


def main() -> int:
    crates = cargo_folders()
    groups = [
        ("Python packages in the helper", notices.python_rows(), lambda row: python_texts(row[0])),
        (
            "JavaScript packages in the app",
            notices.npm_rows(),
            lambda row: _from_folder(ROOT / "app" / "node_modules" / row[0]),
        ),
        (
            "Rust crates in the app shell",
            notices.cargo_rows(),
            lambda row: _from_folder(crates.get((row[0], row[1]), Path("missing"))),
        ),
    ]
    rule = "=" * 78
    out = [
        "OpenLocate: licences of the third-party software it is built from",
        "",
        "OpenLocate itself is licensed under the GNU General Public License, version 3 or",
        "later (LICENSE.txt in this folder). Each package below keeps its own licence.",
        "",
    ]
    missing: list[str] = []
    standard: dict[str, str] = {}
    count = 0
    for title, rows, texts_for in groups:
        out += [rule, title, rule, ""]
        for row in rows:
            name, version, licence, _home = row
            texts = texts_for(row)
            out += ["-" * 78, f"{name} {version}", f"Licence: {licence}", "-" * 78, ""]
            if not texts:
                missing.append(f"{name} {version} ({licence})")
                out += [POINTER, ""]
                continue
            for file_name, text in texts:
                out += [f"[{file_name}]", "", text, ""]
                for heading, start in COPIED_STANDARD:
                    if heading not in standard and text.lstrip().startswith(start):
                        standard[heading] = text
            count += 1

    out += [rule, "Standard licence texts", rule, ""]
    out += ["MIT License", "", MIT, "", "BSD 3-Clause License", "", BSD3, ""]
    for heading, _start in COPIED_STANDARD:
        if heading not in standard:
            print(f"no copy of the {heading} text was found to include", file=sys.stderr)
            return 1
        out += [heading, "", standard[heading], ""]
    gpl = (ROOT / "LICENSE").read_text(encoding="utf-8").strip()
    out += ["GNU General Public License, Version 3", "", gpl, ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8", newline="\n")
    total = sum(len(rows) for _, rows, _ in groups)
    print(
        f"wrote {OUT.relative_to(ROOT)}: texts for {count} of {total} packages, "
        f"{OUT.stat().st_size / 1e6:.1f} MB"
    )
    if missing:
        print(f"{len(missing)} package(s) ship no licence file and point to the standard texts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
