# OpenLocate

OpenLocate is a free, open-source desktop app that makes your own iPhone or iPad report a
location you choose. Type a start and an end address, pick walking, cycling or driving, and
the device travels that route along real roads in real time. You can also jump straight to a
place.

No account, no Apple ID, no jailbreak, no servers of ours, no telemetry. The device must be
connected by USB cable the whole time.

"OpenLocate" is a working name and may change.

## Status: early, tested on one device

This is an early version. Please read this before relying on it.

- **Tested:** Windows 11 with one iPad (iPadOS 27.2) over USB: connecting, jumping to a place,
  travelling a route, pausing, stopping and resetting.
- **Not tested:** any iPhone, other iOS versions, a device that has never been connected
  before, and macOS. They are expected to work but nobody has tried.
- **Not supported:** Wi-Fi (the cable must stay in), iOS 17.0 to 17.3, and iOS 16 or earlier.
- **Known rough edge:** after you stop, the device can keep showing the old place for a few
  minutes, and a device without GPS (a Wi-Fi-only iPad) may need its Wi-Fi turned off and on,
  or a restart, to find its real position again.

Not built yet: picking places by clicking the map, routes with more than two stops, GPX
playback, scheduled location changes and a settings screen.

## What you need

- A Windows 10 or 11 PC.
- The **Apple Devices** app from the Microsoft Store (or iTunes). It provides Apple's USB
  connection.
- An iPhone or iPad on iOS 17.4 or later, and its USB cable.
- An internet connection.

## Install

Download the installer from this repository's Releases page and run it. It installs for your
user account only and does not ask for administrator rights.

The installer is not code-signed yet, so Windows shows "Windows protected your PC". Choose
"More info", then "Run anyway". Before you do, compare the file's SHA-256 checksum with the
one published next to the download.

## Set up your device (once)

1. Open the Apple Devices app once, then plug the device in and unlock it.
2. When the device asks **Trust This Computer?**, tap Trust and enter your passcode.
3. In OpenLocate press **Find devices**, then **Connect**. The first try may say Developer
   Mode is off; that is expected, and it makes the switch appear on the device.
4. On the device open Settings, Privacy & Security, **Developer Mode**, turn it on, restart
   when asked, and confirm after the restart.
5. Press **Connect** again. The first connection takes a little longer.

Developer Mode lowers some of the device's protections. Turn it off again in Settings when
you stop using OpenLocate.

## Use it

1. Type a start and an end, pressing Enter or **Search** after each, or use **Start from my
   location**.
2. Choose **Walk**, **Bike** or **Drive** and press **Get route**.
3. Press **Start**. Pause, resume or stop at any time.
4. To go back to your real location, press **Reset to real location**, close the app, or
   unplug the cable.

While a location is faked, every app on the device sees it, including Find My, Maps and the
clock's time zone.

## Build it yourself

You need Python 3.10 or newer, Node 22 and Rust 1.90 or newer. See `sidecar/README.md` and
`app/README.md` for the details.

On Windows, put the repository in a folder with a short path, such as `C:\dev\openlocate`.
Some of the Python packages have long file names, and installing fails with "No such file or
directory" when the full path goes past Windows' 260-character limit.

    cd sidecar
    python -m venv .venv
    .venv/Scripts/pip install -e ".[dev,build]"        (macOS, Linux: .venv/bin/pip)
    cd ../app
    npm install
    npm run tauri dev                                   (runs the app from source)

To build the installer, from the repository root:

    sidecar/.venv/Scripts/python.exe scripts/build_installer.py

It runs all tests, builds everything and prints the installer's checksum.

## Try the sidecar without an iPhone

For developers. You need Python 3.10 or newer. Run these in a terminal.

1. Go to the sidecar folder and create a virtual environment:

       cd sidecar
       python3 -m venv .venv

2. Install the sidecar with its developer tools (on Windows, use `.venv\Scripts\pip`):

       .venv/bin/pip install -e ".[dev]"

3. Run the tests:

       .venv/bin/python -m pytest -q

4. Start the sidecar with the fake phone:

       .venv/bin/python -m openlocate --backend mock

5. Type a request and press Enter:

       {"jsonrpc":"2.0","id":1,"method":"device.list"}

   You should get one line of JSON back that includes `"id":1`.

6. Press Ctrl+D to stop. On Windows, press Ctrl+Z and then Enter.

On Windows, the interpreter is `.venv\Scripts\python.exe`.

## Repository layout

- `sidecar/`: Python logic. See `sidecar/README.md` for setup and checks.
- `app/`: Tauri 2 shell (Rust) and React UI. See `app/README.md` for setup and checks.
- `protocol/contract.json`: the message contract that both test suites check.
- `scripts/`: building the installer and the third-party licence lists.
- `docs/ARCHITECTURE.md`: decisions and the reasons for them. `docs/specs/`: task specs.
- `docs/RELEASE_PLAN.md`: the plan for releases and the safety rules they must keep.
- `docs/LEGAL.md`: what distributing the app requires, and what is still open.

## Outside services

The app contacts these services and no others. `PRIVACY.md` says what each one is sent.

- Map tiles and the map style from OpenFreeMap (`tiles.openfreemap.org`), while the map
  screen is open.
- Address search from the public Nominatim API, when you press Search or Enter (the text you
  searched for is sent). Another server can be set with `OPENLOCATE_SEARCH_URL`. Its usage policy
  (<https://operations.osmfoundation.org/policies/nominatim/>) limits the whole application to
  one request per second, summed over all users, forbids search-as-you-type, and requires an
  identifying User-Agent. A growing project will need a proxy or another provider.
- Routing from the FOSSGIS OSRM servers at `routing.openstreetmap.de`, when you get a route. The start and end points of the route are sent to that server.
  It is a free community service with no uptime promise; the sidecar sends at most one request
  a second and keeps routes it has already fetched on disk. Another server can be set with
  `OPENLOCATE_ROUTER_WALK_URL`, `OPENLOCATE_ROUTER_BIKE_URL` and `OPENLOCATE_ROUTER_DRIVE_URL`.
- GitHub (`raw.githubusercontent.com`, the `doronz88/DeveloperDiskImage` repository), to
  download the developer disk image the first time a device is connected. This is done by
  pymobiledevice3.
- Apple's signing server, for the developer disk image on iOS 17 and later.

## Use with your own device only

Use this app only with your own device. Some apps and games, such as Pokémon Go, ban location
spoofing and may suspend accounts. Follow the terms of service of any app you use. You take the
risk of any account action. The full terms are in `TERMS.md`.

## License and legal

Copyright (C) 2026 OpenLocate

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3 of
the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
the GNU General Public License for more details.

The full licence is in `LICENSE`. The project bundles pymobiledevice3, which is also
GPL-3.0-or-later.

- `TERMS.md`: terms of use and disclaimer, in plain words.
- `PRIVACY.md`: what stays on your computer and what is sent to which service.
- `THIRD_PARTY_NOTICES.md`: the third-party software the app is built from, with licences.
- `docs/LEGAL.md`: notes for maintainers on what distributing the app requires, including
  questions that are still open.

OpenLocate is not affiliated with or endorsed by Apple Inc. iPhone and iPad are trademarks of
Apple Inc.
