"""Build the standalone helper that ships inside the app.

    .venv/Scripts/python.exe -m pip install -e ".[build]"
    .venv/Scripts/python.exe packaging/build.py

The result is the folder sidecar/dist/openlocate-sidecar/, holding openlocate-sidecar(.exe)
and everything it needs. The app's bundle copies that folder (see tauri.conf.json), so users
do not need Python. It is a one-folder build on purpose: a one-file build unpacks itself on
every start and leaves a second process behind when the app stops it (ARCHITECTURE.md 2.4).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIDECAR = HERE.parent
NAME = "openlocate-sidecar"

# Parts of pymobiledevice3 the helper never uses. Leaving them out makes the download smaller
# and keeps tools such as the web inspector and the remote shell out of what we ship.
EXCLUDED = [
    "pymobiledevice3.cli",
    "pymobiledevice3.resources.serve_web",
    "pymobiledevice3.resources.webinspector",
    "pymobiledevice3.services.web_protocol",
    "pymobiledevice3.services.webinspector",
    "IPython",
    "pytest",
    "tkinter",
    "matplotlib",
    "numpy",
]

# Libraries that look their own version up at import time. PyInstaller leaves that
# information out unless told to keep it, and the import then fails.
NEEDS_METADATA = ["pyimg4"]


def main() -> int:
    dist = SIDECAR / "dist"
    work = SIDECAR / "build" / "pyinstaller"
    shutil.rmtree(dist / NAME, ignore_errors=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(HERE / "sidecar_entry.py"),
        "--name",
        NAME,
        "--onedir",
        "--console",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        # The stubs come first so they replace the real packages of the same name.
        "--paths",
        str(HERE / "stubs"),
        "--paths",
        str(SIDECAR / "src"),
    ]
    for module in EXCLUDED:
        command += ["--exclude-module", module]
    for package in NEEDS_METADATA:
        command += ["--copy-metadata", package]
    subprocess.run(command, check=True, cwd=SIDECAR)

    unwanted = [f.name for f in (dist / NAME).rglob("*") if f.name.lower() == "wintun.dll"]
    if unwanted:
        print("the build contains wintun.dll, which must not be shipped", file=sys.stderr)
        return 1

    built = dist / NAME / (NAME + (".exe" if sys.platform == "win32" else ""))
    if not built.exists():
        print(f"build finished but {built} is missing", file=sys.stderr)
        return 1
    size_mb = sum(f.stat().st_size for f in (dist / NAME).rglob("*") if f.is_file()) / 1e6
    print(f"built {built} ({size_mb:.0f} MB in the folder)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
