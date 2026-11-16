# Legal notes for maintainers

Written 15 November 2026 for whoever publishes OpenLocate. It was prepared without a lawyer.
It records what the project has to do when it gives the app to other people, what is already
done, and what is still open. Treat the open items as questions for a lawyer, not as settled.

## The documents and what each is for

| File | Who it is for | Purpose |
|---|---|---|
| `LICENSE` | Everyone | The GNU GPL, version 3: the licence the app is distributed under |
| `TERMS.md` | Users | Plain-language terms of use, acceptable use, no warranty, no liability, trademarks |
| `PRIVACY.md` | Users | What stays on the computer and what is sent to which outside service |
| `THIRD_PARTY_NOTICES.md` | Everyone | Every third-party package and its licence (generated) |
| `docs/LEGAL.md` | Maintainers | This file |

## 1. The app's own licence: GPL-3.0-or-later

The app links pymobiledevice3, which is GPL-3.0-or-later, so the whole app must be
distributed under the GPL. That is the licence already chosen. What it requires when a build
is handed to anyone:

- **Ship the licence.** Include `LICENSE` in every download and installer.
- **Offer the source.** The exact source of each released build must be available to
  whoever gets the binary: publish the repository, tag every release, and link the tag from
  the download page. That covers the Python sidecar, the app, the build scripts and the
  packaging configuration.
- **Keep the notices.** Do not remove copyright or licence notices from third-party code.
- **Say there is no warranty** and where the licence is. The app's footer and `TERMS.md` do
  this.
- **Do not add restrictions.** Nothing in `TERMS.md` may limit what the GPL allows; it is
  written as guidance and a disclaimer, not as extra licence conditions. Keep it that way.
- **App stores.** The GPL's terms conflict with the usual terms of Apple's App Store and can
  conflict with the Microsoft Store. Distribute direct downloads.

Contributions from other people come in under the same licence. Decide before accepting
outside contributions whether to ask contributors to sign off their commits (a Developer
Certificate of Origin); without everyone's agreement the licence can never be changed later.

## 2. Third-party software

`THIRD_PARTY_NOTICES.md` lists every package the app is built from. On 15 November 2026 that
was 88 Python packages, 29 JavaScript packages and 420 Rust crates. All state a licence that
can be combined with GPL-3.0: MIT, BSD, ISC, Apache-2.0, MPL-2.0, Unicode, Zlib, PSF, LGPL-3.0
and GPL-3.0 itself. Two Python packages (ASGIMiddlewareStaticFile and ASGIWebDAV) name no
licence in their metadata; their bundled licence files are MIT.

Before each release:

1. Run `scripts/third_party_notices.py` and commit the result.
2. Read the script's last line: it names any package with no stated licence. Check those by
   hand.
3. Look for a licence that is not on the list above. A package under a non-free, "source
   available" or non-commercial licence, or under AGPL, needs a decision before it ships.

**Left out on purpose: `wintun.dll`.** The device library depends on `pytun_pmd3`, which
ships WireGuard's prebuilt Wintun driver library under its own "Prebuilt Binaries License"
(not an open-source licence). OpenLocate does not use it, and the standalone helper is built
without it (`sidecar/packaging/stubs/`). Keep it out: shipping it inside a GPL program is a
question nobody has answered for this project.

**The helper's packaging.** The standalone helper is made with PyInstaller. Its bootloader is
GPL with an exception that allows bundling programs under any licence, so it adds no
condition of its own.

**Open: licence texts in the installer.** MIT, BSD, Apache and similar licences require
their own text and copyright lines to travel with binaries. The notices file lists names and
licences only. The packaging step (Milestone 6) must collect the licence files of everything
it bundles (for example with `pip-licenses`, `cargo-about` and `license-checker`) and include
them in the installer, with an "open-source licences" entry in the app.

## 3. Map data, tiles, search and routing

| What | From | What it requires |
|---|---|---|
| Map data | OpenStreetMap contributors, under the Open Database Licence | Visible credit "© OpenStreetMap contributors". The map shows it, and so does the side panel. |
| Map tiles and style | OpenFreeMap, using the OpenMapTiles schema | Visible credit to OpenFreeMap and OpenMapTiles. The map shows it. Free for any use, no key. |
| Address search | Nominatim on the OpenStreetMap Foundation's servers | See the policy below. |
| Routes | OSRM on FOSSGIS servers (`routing.openstreetmap.de`) | See the policy below. |

**Open: Nominatim's usage policy** (<https://operations.osmfoundation.org/policies/nominatim/>).
The public server allows at most one request a second **added up over all users of the
app**, forbids search-as-you-type, wants results cached, and asks for a User-Agent that
identifies the app with a way to reach its author. The app follows the first three per
installation and sends `OpenLocate/<version>` with no contact. Two things to do before a
public release: put the project's web address or an email in the User-Agent
(`sidecar/src/openlocate/net.py`), and plan for growth. With more than a handful of users the
shared limit is exceeded and the project must move to its own Nominatim, a paid geocoder, or
ask the operators. The server's address can already be changed without a new release.

**Open: FOSSGIS routing.** The server's about page
(<https://routing.openstreetmap.de/about.html>, read 15 November 2026) gives this excerpt of
its usage policy: show the required attribution and a link to "fix the map"
(<https://www.openstreetmap.org/fixthemap>); send a valid user agent; at most one request a
second; no scraping and no heavy usage. The app shows the attribution and the fix-the-map
address in its side panel, identifies itself, and limits itself to one request a second per
installation. The full policy is in German at
<https://www.fossgis.de/arbeitsgruppen/osm-server/nutzungsbedingungen/> and has not been
read. As with search, "no heavy usage" is measured across everyone using the app, so a
distributed app should ask the operators (fossgis-routing-server@openstreetmap.de) or run its
own OSRM server. The addresses can already be changed.

## 4. Apple

- **No Apple code is shipped.** The app talks to the device through Apple's own developer
  interfaces by way of pymobiledevice3. It does not jailbreak the device or get round a
  technical protection.
- **Open: the developer disk image.** iOS needs Apple's developer disk image mounted before
  it accepts location simulation. pymobiledevice3 downloads it from a third-party GitHub
  repository (`doronz88/DeveloperDiskImage`), and on iOS 17 and later Apple's own server
  signs it for the device. The image is Apple's copyrighted software, normally obtained with
  Xcode under Apple's licence. OpenLocate does not host or bundle it, but it does cause the
  download. Whether that is acceptable for a distributed app is a question for a lawyer. A
  more cautious design lets the user point the app at an image from their own Xcode.
- **Apple's terms.** Using developer features outside app development may be against Apple's
  developer agreements for people who have accepted them. `TERMS.md` leaves that to the user.
- **Trademarks.** "iPhone", "iPad" and "Apple" may be used to say what the app works with.
  Do not use Apple's logos, product pictures or a name or icon that could be taken for an
  Apple product.

## 5. The purpose of the app

Faking a location is lawful in general, but it is what the app is for, and that brings risk
the documents cannot remove:

- **Other companies' terms.** Games and services forbid it. Do not advertise the app as a
  way to cheat in a named game or to get round a named service; that invites claims against
  the project, not only against users. The README and `TERMS.md` mention Pokémon GO only as a
  warning.
- **Misuse.** `TERMS.md` lists fraud, stalking and evading legal duties as forbidden uses.
  That helps show intent; it does not make the project immune.
- **Local law.** Some countries restrict tools that falsify location or device data. This
  has not been checked country by country.

## 6. Privacy law

The project collects no personal data and runs no servers, so it is not a data controller
for what users do in the app. `PRIVACY.md` tells users which outside services receive what.
Keep it true: any new service, any telemetry, any crash reporting or update check changes
the picture and needs a new look (in the EU and UK, a legal basis and possibly consent).

## 7. Things to settle before a public release

1. **Who publishes it.** Name the publisher (a person or an organisation) and a public way
   to reach them in the README, `PRIVACY.md` and `TERMS.md`. They currently say "the
   project's issue tracker".
2. **The name.** "OpenLocate" is a placeholder. Search trademark registers and app stores for
   the final name before using it.
3. **A copyright line.** Add "Copyright (C) <year> <owner>" and the standard GPL notice to
   the README and, ideally, the top of source files.
4. **Nominatim contact and capacity** (section 3).
5. **FOSSGIS terms** (section 3).
6. **The developer disk image** (section 4).
7. **Licence texts in the installer** (section 2).
8. **Code signing.** Unsigned installers trigger warnings on Windows and are blocked on
   macOS. Signing needs paid certificates in the publisher's legal name, and Apple's
   notarisation needs an Apple developer account, whose agreement should be read with
   section 4 in mind.
9. **A lawyer's review** of `TERMS.md`, the disk image question and the app's purpose in the
   countries where it will be offered.
