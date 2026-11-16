# Privacy

Last updated: 15 November 2026.

OpenLocate is a desktop app that runs on your own computer. The people who make it run no
servers for it and collect nothing from you: no account, no sign-up, no analytics, no
telemetry, no crash reports, no advertising.

To do its job the app does contact some services run by other organisations. This page lists
each one, what it is sent, and when. Any service you contact can also see your internet (IP)
address, as with any website.

## What stays on your computer

- **Your computer's location.** The map screen asks your operating system where the computer
  is, to open the map there. It is used only inside the app. It leaves your computer in one
  case: if you press "Start from my location" and then get a route, it is sent to the
  routing service as the start of that route (see below).
- **The fake locations you choose.** They are sent to your own iPhone or iPad over the USB
  cable, and to nobody else.
- **A log file.** It records what the app did (connections, each location sent to your device,
  errors) to help find problems. It does not record what you typed into the search boxes. It
  is kept on your computer, limited to a few megabytes, and never uploaded. Its path is shown
  on the Developer console tab. If you attach it to a bug report, read it first: it contains
  your device's name and identifier and the coordinates you used.
- **Saved routes.** Routes already fetched are kept in a cache folder on your computer so
  they need not be fetched again. You can delete that folder at any time.
- **Your device's pairing.** Connecting uses the "Trust This Computer" pairing that Apple's own
  software keeps on your computer.

## What is sent to other services

| When | Sent to | What is sent |
|---|---|---|
| The map is on screen | OpenFreeMap (`tiles.openfreemap.org`) | Which map areas you look at |
| You press Search or Enter in an address box | Nominatim, run by the OpenStreetMap Foundation (`nominatim.openstreetmap.org`) | The text you searched for |
| You press "Get route", or load a road route | FOSSGIS routing servers (`routing.openstreetmap.de`) | The start and end coordinates and whether you walk, cycle or drive |
| You connect a device for the first time, or after an iOS update | GitHub (`raw.githubusercontent.com`) | A request for the developer disk image matching your iOS version |
| The same, on iOS 17 and later | Apple (its signing server) | Identifiers of your device, so Apple can sign the disk image for it |

The last two are done by pymobiledevice3, the open-source library the app uses to talk to
the device.

Each of those organisations handles what it receives under its own privacy policy, not this
one:

- OpenFreeMap: <https://openfreemap.org/privacy/>
- OpenStreetMap Foundation (Nominatim): <https://osmfoundation.org/wiki/Privacy_Policy>
- FOSSGIS (in German): <https://www.fossgis.de/datenschutzerklärung>. Its routing server's
  own page says each route request is saved in the server's log file:
  <https://routing.openstreetmap.de/about.html>
- GitHub: <https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement>
- Apple: <https://www.apple.com/legal/privacy/>

## Choices you have

- Enter coordinates on the Developer console tab instead of searching, and no search text is
  sent.
- Do not press "Start from my location", and your computer's location is never sent.
- Point the app at search and routing servers you run yourself with the
  `OPENLOCATE_SEARCH_URL`, `OPENLOCATE_ROUTER_WALK_URL`, `OPENLOCATE_ROUTER_BIKE_URL` and
  `OPENLOCATE_ROUTER_DRIVE_URL` environment variables.
- Refuse the operating system's location permission. The app then asks you to search for a
  start instead.

## Children

The app is not directed at children and collects nothing from anyone.

## Changes and questions

If the app starts contacting a new service, this page and the "Outside services" section of
the README are updated in the same release. Questions and corrections go to the project's
issue tracker.
