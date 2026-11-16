# Release plan: a download anyone can install

Decided 15 November 2026: OpenLocate ships as a download for ordinary users, from GitHub
Releases and optionally a small website that links to them. This file is the plan. Update it
as steps are done or decisions change.

## Where it stands

- An installer can be built on Windows (see Stage 1). It has not been tried on a PC without
  developer tools.
- Tested on one Windows 11 PC with one iPad (iPadOS 27.2). Not tested: an iPhone, a device
  that has never been connected, another PC, macOS.
- No public repository yet. `origin` is a local folder.

## Stage 1: a Windows installer that works on a clean PC

1. **Bundle the helper.** Done 15 November 2026: `sidecar/packaging/build.py` builds a
   one-folder PyInstaller bundle (about 70 MB) that the app ships through `bundle.resources`.
   The standalone helper was run against the iPad: connect, a road route, reset.
2. **Start the bundled helper in release builds.** Done 15 November 2026. Killing the app
   abruptly was tried while a trip was playing: the helper noticed its input close, ended the
   device session and exited within 4 seconds. A Windows Job Object would cover the rarer
   case of a helper that hangs; it is not built.
3. **Build the installer.** Done 15 November 2026: `npm run tauri build -- --bundles nsis` in
   `app/` writes `OpenLocate_<version>_x64-setup.exe` (about 30 MB) with the helper,
   `LICENSE`, `TERMS.md`, `PRIVACY.md` and `THIRD_PARTY_NOTICES.md` inside. The release build
   was run from the build folder against the iPad (search, route, travel, my location). The
   installer itself has not been run. Still missing from it: the full third-party licence
   texts.
4. **First-run guidance in the app** for what a new user hits before anything works:
   Apple Devices app missing, device not trusted, Developer Mode off, device locked. Today
   these are error banners; they should be a short checklist with the fix for each.
5. **Show the terms once** on first start, with a button to accept, and an About screen with
   the licence, the open-source notices and the version.
6. **Test on a clean Windows PC** (no Python, Node.js or Rust) with a device that has never
   been connected, and with an iPhone.

Done when: a person with no developer tools downloads one file, installs it, and travels a
route on their own iPhone or iPad by following only what the app tells them.

## Safety rules for what we ship

The app is handed to people who cannot check it themselves, so each release must keep these
true. The first five were checked on 15 November 2026; re-check them when packaging changes.

- **No administrator rights.** The installer installs for the current user only. The app and
  its helper never ask for elevation.
- **No drivers, services or start-up entries.** The helper reaches the device through an
  in-process tunnel. The kernel network driver that the device library can use (`wintun.dll`)
  is deliberately left out: `sidecar/packaging/stubs/` replaces the package that loads it,
  and the build fails if the file appears in the bundle.
- **Nothing listens on the network.** The helper talks to the app over its own standard
  input and output, not a port. While connected to a device it holds two UDP sockets bound to
  `127.0.0.1` for the internal tunnel; they cannot be reached from another computer.
- **Fewer tools than the library has.** The device library can do far more than set a
  location (file access, app install, web inspector, shell). The helper exposes only the
  commands in `protocol/contract.json`, and the build leaves out the library's command-line
  tools and web inspector.
- **Only the listed services are contacted** (`PRIVACY.md`). The app's content security
  policy allows the map tile server and nothing else; the helper's requests are in two files,
  `net.py` callers and the device library's disk-image download. No telemetry, no automatic
  update, no crash upload. (`opentelemetry-api` is installed as an unused dependency of a
  dependency; no exporter is present.)
- **The helper must not outlive the app.** It exits when the app closes its input, and the
  app kills it after 2 seconds otherwise. When the app was killed outright, the helper still
  exited by itself and the device stopped faking its location.
- **The app's pages get no device permissions except location.** The shell answers every
  permission request itself: location is allowed (the operating system's own location
  setting still decides), and camera, microphone, notifications, clipboard and file access
  are refused.
- **Builds come from public source.** Until builds are automated and signed, publish a
  SHA-256 checksum with each installer and say plainly that Windows will warn about an
  unknown publisher. PyInstaller programs are sometimes flagged by antivirus tools by
  mistake; check each release on a multi-engine scanner before publishing.
- **Dependencies should be pinned** to exact versions that have been public for at least two
  weeks, so a freshly published bad release cannot slip into a build. Not true yet for the
  helper: `pymobiledevice3` is a version range, and 11.54.0 was three days old when adopted.
  Still to do: a lock file for the helper's Python packages, used by the installer build.

## Stage 2: publishing

1. **Public GitHub repository** with the source, tagged releases, and the installer attached
   to each release. This also meets the GPL's source-offer duty.
2. **Automated builds** (GitHub Actions) that run the tests and produce the installer from a
   tag, so every download matches public source.
3. **Checksums** published with each release.
4. **A simple website** (GitHub Pages is enough): what it does, requirements, download
   button to the latest release, setup steps, terms and privacy.
5. **Update notice.** At minimum the site and README say how to update. An in-app check for
   new versions contacts a server, so it must be added to `PRIVACY.md` if built.

## Stage 3: things that cost money or need a decision

These gate a wide release, not a small trial with people you know.

1. **Windows code signing.** Unsigned installers show a SmartScreen warning ("Windows
   protected your PC") that most people will not click through. Signing needs a paid
   certificate in the publisher's name.
2. **Search and routing capacity.** The free services allow about one request a second
   across all users together (see `docs/LEGAL.md`). Options: run our own servers, pay for a
   provider, or get the operators' agreement. Without one of these, a public release will
   break their rules as soon as it has real use.
3. **The developer disk image question** and a lawyer's look at `TERMS.md`.
4. **Publisher identity and contact**, the final name, and a trademark search.

## Stage 4: macOS

Needs a Mac to build and test on. Known work: the location-permission declaration, checking
the map and layout in Safari's engine, choosing the device connection method, and Apple's
signing and notarisation (a paid Apple developer account). Ship Windows first.

## Suggested order

Stage 1 steps 1 to 3, then a private trial with two or three people (Stage 1 step 6 in
practice), then Stage 1 steps 4 and 5 from what the trial shows, then Stage 2. Stage 3 runs
alongside, because certificates and server decisions take calendar time.
