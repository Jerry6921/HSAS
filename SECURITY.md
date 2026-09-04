# Security policy

Keep HKU passwords, MFA codes, cookies, Moodle sesskeys, browser profiles,
tokens, private course files, extracted text sidecars, and information.json
inside the private authentication and course-data boundary.

Before sharing a diagnostic, remove personal paths and course content. Security
reports should identify the affected HIQS version/commit and provide the smallest
reproduction built from synthetic data.

The updater accepts an HTTPS release only after the user pins the full commit
reported by a dry run. Dependency changes are intentionally outside the in-place
update transaction.
