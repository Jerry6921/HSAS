# Security policy

Keep HKU passwords, MFA codes, cookies, Moodle sesskeys, Moodle/SIS browser profiles,
tokens, private course files, extracted text sidecars, and information.json
inside the private authentication and course-data boundary.

Before sharing a diagnostic, remove personal paths and course content. Security
reports should identify the affected HIQS version/commit and provide the smallest
reproduction built from synthetic data.

The updater resolves the official GitHub `main` branch to a full commit before
confirmation. Apply succeeds only when that exact commit remains current, the
checkout is clean, and the update is a fast-forward. Dependency changes are
intentionally rejected from the in-place update transaction and require a
separate Agent-managed environment upgrade.

## Update trust model

The updater does **not** verify commit or tag signatures and does not compare a
release checksum. Its trust anchors are the GitHub account that can push to
`Jerry6921/HSAS` and the operating system certificate store. A compromised
account (or an installed root certificate) can therefore ship code that the
updater will accept after a human confirmation. Treat the update prompt as
"this exact commit came from the repository account", not as "this code was
cryptographically released".

## Apple helper integrity

The EventKit helper is compiled locally and ad-hoc signed; its integrity stamp
covers the Swift source, the build target and the compiled executable, so a
replaced binary forces a rebuild. This is a drift detector: the stamp and the
binary live in the same user-writable directory, so it does not defend against
an attacker already running as that user. Verified EventKit readback proves the
local macOS store, not iCloud server delivery.
