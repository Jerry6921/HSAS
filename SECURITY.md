# Security policy

Do not report HKU passwords, MFA codes, cookies, Moodle sesskeys, browser profiles,
tokens, private course files, Student Profiles, Execution Logs, or Integrated
Plans in a public issue.

Before sharing a diagnostic, remove personal paths and course content. Security
reports should identify the affected HSAS version/commit and provide the smallest
reproduction that does not contain authentication or student data.

The updater accepts an HTTPS release only after the user pins the full commit
reported by a dry run. Dependency changes are intentionally outside the in-place
update transaction.
