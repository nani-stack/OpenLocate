"""Build the OpenLocate installer from a clean checkout, in the right order.

    sidecar/.venv/Scripts/python.exe scripts/build_installer.py        (Windows)

Needs: the sidecar's virtualenv with `pip install -e ".[dev,build]"`, `npm install` done in
app/, and a Rust toolchain. Steps:

1. Run the three test suites. A failing test stops the build.
2. Build the standalone helper (it refuses to build if the installed Python packages differ
   from sidecar/packaging/requirements.lock).
3. Rewrite THIRD_PARTY_NOTICES.md and collect the third-party licence texts.
4. Build the app and its installer with the installer-only settings in
   app/src-tauri/tauri.bundle.conf.json.
5. Print the installer's path, size and SHA-256 checksum. Publish the checksum next to the
   download so people can check what they got.

Pass --skip-tests to leave out step 1 while working on the packaging itself.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "sidecar"
APP = ROOT / "app"
TAURI = APP / "src-tauri"
BUNDLES = TAURI / "target" / "release" / "bundle"


def run(step: str, command: list[str], cwd: Path) -> None:
    print(f"\n== {step}", flush=True)
    program = shutil.which(command[0]) or command[0]
    subprocess.run([program, *command[1:]], cwd=cwd, check=True)


def main() -> int:
    python = sys.executable
    if "--skip-tests" not in sys.argv[1:]:
        run("sidecar tests", [python, "-m", "pytest", "-q"], SIDECAR)
        run("app tests", ["npm", "test"], APP)
        run("app type check", ["npm", "run", "typecheck"], APP)
        run("app shell tests", ["cargo", "test", "--workspace", "--quiet"], TAURI)

    run("standalone helper", [python, "packaging/build.py"], SIDECAR)
    run("third-party notices", [python, "scripts/third_party_notices.py"], ROOT)
    run("third-party licence texts", [python, "scripts/third_party_licenses.py"], ROOT)

    bundle = "nsis" if sys.platform == "win32" else "dmg" if sys.platform == "darwin" else "deb"
    run(
        "app and installer",
        ["npm", "run", "tauri", "--", "build", "--bundles", bundle,
         "--config", "src-tauri/tauri.bundle.conf.json"],
        APP,
    )

    installers = sorted(
        (p for p in BUNDLES.rglob("*") if p.suffix in (".exe", ".dmg", ".deb") and p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    if not installers:
        print("the build finished but no installer was found", file=sys.stderr)
        return 1
    installer = installers[-1]
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    print(f"\ninstaller: {installer}")
    print(f"size:      {installer.stat().st_size / 1e6:.1f} MB")
    print(f"SHA-256:   {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
