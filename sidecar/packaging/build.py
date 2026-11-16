"""Build the standalone helper that ships inside the app.

    .venv/Scripts/python.exe -m pip install -e ".[build]"
    .venv/Scripts/python.exe packaging/build.py
    .venv/Scripts/python.exe packaging/build.py --write-lock    (after changing a package)

The result is the folder sidecar/dist/openlocate-sidecar/, holding openlocate-sidecar(.exe)
and everything it needs. The app's bundle copies that folder (see tauri.conf.json), so users
do not need Python. It is a one-folder build on purpose: a one-file build unpacks itself on
every start and leaves a second process behind when the app stops it (ARCHITECTURE.md 2.4).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement

HERE = Path(__file__).resolve().parent
SIDECAR = HERE.parent
NAME = "openlocate-sidecar"
LOCK = HERE / "requirements.lock"

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


def installed_versions() -> dict[str, str]:
    """Every package the helper needs at run time, with the version installed here."""
    environment = default_environment()
    found: dict[str, str] = {}
    queue = ["openlocate"]
    while queue:
        try:
            dist = metadata.distribution(queue.pop())
        except metadata.PackageNotFoundError:
            continue
        key = dist.metadata["Name"].lower().replace("_", "-")
        if key in found:
            continue
        found[key] = dist.version
        for text in dist.requires or []:
            requirement = Requirement(text)
            if requirement.marker is None or requirement.marker.evaluate(
                {**environment, "extra": ""}
            ):
                queue.append(requirement.name)
    found.pop("openlocate", None)
    return found


def read_lock() -> dict[str, str]:
    locked: dict[str, str] = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            name, _, version = line.partition("==")
            locked[name] = version
    return locked


def write_lock() -> int:
    versions = installed_versions()
    lines = [
        "# Exact versions of everything inside the standalone helper. Written by",
        "# `packaging/build.py --write-lock`; the build refuses to run if the environment",
        "# differs. To update a package: install the new version (one that has been public",
        "# for at least two weeks), run the tests, rewrite this file, and review the diff.",
    ]
    lines += [f"{name}=={version}" for name, version in sorted(versions.items())]
    LOCK.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {LOCK.name} with {len(versions)} packages")
    return 0


def check_lock() -> bool:
    """True if what is installed is exactly what the lock file lists."""
    locked, installed = read_lock(), installed_versions()
    problems = [
        f"  {name}: locked {locked.get(name, 'absent')}, installed {installed.get(name, 'absent')}"
        for name in sorted(set(locked) | set(installed))
        if locked.get(name) != installed.get(name)
    ]
    if problems:
        print("the environment does not match packaging/requirements.lock:", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        print(f"install the locked versions with: pip install -r {LOCK}", file=sys.stderr)
    return not problems


def main() -> int:
    if "--write-lock" in sys.argv[1:]:
        return write_lock()
    if not check_lock():
        return 1
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
