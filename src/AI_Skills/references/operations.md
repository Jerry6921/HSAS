# Operations, authority, and freshness

Read this reference before running login, synchronization, or planning commands, or when deciding whether local data is sufficiently current.

## Authority matrix

| Operation | Default authority | Required behavior |
|---|---|---|
| Read normalized local JSON and analyzed text | Allowed for an in-scope answer | Read the minimum relevant files and do not expose private content unnecessarily |
| `hsas list-status` | Allowed as a read-oriented diagnostic | Use when status materially affects the request |
| `hsas login` | Requires a login request or an expired-session blocker | The user completes SSO/MFA; stop after one failed verification and never request credentials |
| `hsas sync-courses COURSE` | Allowed when the user asks to sync/refresh that course | Prefer the smallest sufficient course scope |
| `hsas sync-courses` for every course | Requires a complete refresh or cross-course need | Do not broaden a single-course request into a full sync |
| Update `student_profile.json` through `hsas profile apply` | Only user-confirmed facts in the request's scope | Follow `data-write-protocols.md`; never edit JSON directly |
| Add/correct `execution_log.json` through `hsas execution` | Only user-confirmed execution facts | Follow `data-write-protocols.md`; preserve stable retry IDs |
| `hsas update-plan` | Allowed after an authorized input change or explicit plan request | Require final validation; never hand-edit the generated plan |
| `hsas migrate-data` | Requires an explicit migration request | Copy and verify only; retain legacy files and report their paths for user review |
| `hsas update-hsas` | Requires an explicit software-update request | Dry-run first, then authorize the exact full commit; preserve personal data and use the package manager when dependencies change |
| Follow an external activity URL or contact a third party | Separate authorization required | Moodle access does not authorize unrelated external access or messaging |
| Submit work, alter Moodle, or create calendar events | Unsupported unless a future explicit capability exists | Do not claim or simulate success |

An ordinary read-only question does not authorize synchronization or local writes. If stronger freshness is desirable but not authorized, answer from the last known good data with a visible timestamp and recommend the smallest refresh.

## Freshness policy

Treat freshness as claim-specific rather than assigning one age to the entire archive.

| Claim or task | Default freshness expectation |
|---|---|
| User asks for “latest/current/now” | Refresh the relevant course when authorized; otherwise state that live verification was not performed |
| Deadline, opening, visibility, or restriction within 7 days | Prefer data collected within 24 hours and direct Moodle activity metadata |
| A weekly or cross-course plan | Prefer every relevant course collected within 24 hours; disclose any stale or failed course |
| Assessment weight, requirements, or policy | Verify the course/semester and source revision; an unchanged syllabus SHA-256 may remain usable |
| Course-material explanation | Use the stored file only when SHA-256 and analysis status identify the analyzed copy; disclose OCR or extraction gaps |
| Historical explanation | Older data may be used when the date and semester are explicit |

These are defaults, not invented facts. A nearer deadline, known course update, user concern, or sync failure warrants stricter treatment. A stable syllabus does not make live activity visibility or DDL current.

## Last-known-good behavior

When an operation fails:

1. Do not overwrite or delete a valid prior archive, Profile, Execution Log, or Plan.
2. Read `sync-report.json` and the relevant `changes/latest.json` before claiming completeness.
3. If a previous archive remains valid, it may support a stale answer only with its `collected_at` timestamp and the failure disclosed.
4. Do not interpret an absent course in a failed batch as course removal.
5. Do not run repeated login or network retries after the same blocker. Stop and ask for the user action that can change the state.
6. If plan generation or validation fails, keep the last valid plan and report the error; never patch the generated JSON around validation.

## Command stopping conditions

- Login redirects away from the configured Moodle host: stop and ask the user to run `hsas login`.
- Dashboard/course selectors return no courses after login: report a selector or discovery issue; do not conclude the student has no courses.
- One course fails during all-course sync: let the batch continue, then report the failed course from `sync-report.json`.
- A file is unavailable, external, or OCR-only: preserve its status and avoid unsupported content claims.
- Planner reports validation errors: do not present the new plan as valid.

## Portable project execution

From `HSAS_ROOT`, prefer the installed command. During development, `.venv/bin/hsas` is an acceptable local equivalent. Do not embed a machine-specific absolute project path in instructions or persisted data.
