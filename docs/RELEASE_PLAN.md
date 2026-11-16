# Release plan: a download anyone can install

Decided 15 November 2026: OpenLocate ships as a download for ordinary users, from GitHub
Releases and optionally a small website that links to them. This file is the plan. Update it
as steps are done or decisions change.

## Where it stands

- Runs only from source (`npm run tauri dev`), which needs Python, Node.js and Rust.
- A release build of the app refuses to start the helper program ("bundled sidecar not
  available yet").
- Tested on one Windows 11 PC with one iPad (iPadOS 27.2). Not tested: an iPhone, a device
  that has never been connected, another PC, macOS.
- No public repository yet. `origin` is a local folder.

## Stage 1: a Windows installer that works on a clean PC

1. **Bundle the helper.** Build the Python sidecar with PyInstaller as a one-folder bundle
   and ship it inside the app through `bundle.resources` (the approach chosen in
   ARCHITECTURE.md 2.4). Open risk: the device tunnel's networking stack may need extra
   PyInstaller settings.
2. **Start the bundled helper in release builds**, and make sure it dies with the app (the
   planned Windows Job Object).
3. **Build the installer** with Tauri's bundler (NSIS `.exe`). Include `LICENSE`,
   `TERMS.md`, `PRIVACY.md` and the third-party licence texts.
4. **First-run guidance in the app** for what a new user hits before anything works:
   Apple Devices app missing, device not trusted, Developer Mode off, device locked. Today
   these are error banners; they should be a short checklist with the fix for each.
5. **Show the terms once** on first start, with a button to accept, and an About screen with
   the licence, the open-source notices and the version.
6. **Test on a clean Windows PC** (no Python, Node.js or Rust) with a device that has never
   been connected, and with an iPhone.

Done when: a person with no developer tools downloads one file, installs it, and travels a
route on their own iPhone or iPad by following only what the app tells them.

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
