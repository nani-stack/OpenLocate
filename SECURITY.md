# Security

OpenLocate talks to a phone over a trusted USB connection, so mistakes here matter.

## Reporting a problem

If you find a security problem, please do not open a public issue with the details. Use
GitHub's private reporting instead: on this repository's page open the **Security** tab and
choose **Report a vulnerability**. Say what you found, how to reproduce it, and which version
you used. You should get a first answer within a week.

Ordinary bugs, including crashes, belong in the normal issue tracker.

## What to expect from a release

Each release is meant to keep the rules in `docs/RELEASE_PLAN.md` ("Safety rules for what we
ship"). In short: no administrator rights, no drivers or background services, nothing
listening on the network, only the outside services listed in `PRIVACY.md`, and a helper
program that stops when the app does. If a release breaks one of these, that is a security
problem; please report it.

Installers are not code-signed yet. Check the SHA-256 checksum published with each download.

## Supported versions

Only the newest release gets fixes.
