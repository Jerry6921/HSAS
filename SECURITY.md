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
