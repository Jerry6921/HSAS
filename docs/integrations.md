# Integration truth table

Every external dependency HIQS talks to, with the exact code that depends on it, the ways
it can fail, and the last time it was **actually verified**.

Rules (see `docs/agents/engineering-management.md` §3):

- **A row without a verified date is an assumption, not a fact.** Never fill one from
  memory, from the vendor's documentation, or from what an agent believes it observed.
- **Verified** means one real authenticated run against the live system produced a
  readable, expected result. A mock, a fixture, a test double, or a green unit test does
  not verify anything here.
- Update the row in the same change that exercises or repairs the integration.
- If a system fails, record the failure mode and the date; a known-broken integration is
  more useful than a blank cell.

## Table

| System | Code | Dependency point | Known failure modes | Last verified |
| --- | --- | --- | --- | --- |
| HKU Moodle | `src/hsas/infrastructure/moodle/` | SSO + MFA session, course activity list, file download links | SSO/MFA session expiry; activity page structure change; per-file download token rotation; rate limiting on bulk download | 2026-10-22, authenticated sync |
| HKU SIS Student Center | `src/hsas/infrastructure/sis/enrollment/` | Current-semester enrolled course list | Term rollover changes the page contract; table structure change; empty-term ambiguity silently returning no courses | 2026-10-22, authenticated sync |
| HKU SIS Course Information | `src/hsas/infrastructure/sis/course_info/` | Official catalogue page per course code | Catalogue URL pattern change; page HTML change breaking text cleanup; unselected course codes returning nothing; course codes absent from the catalogue (BMED2206/BMED2810 stayed in `retry_tasks` after the 2026-10-27 sync) | 2026-10-22, authenticated sync |
| HKU Class Planner | `src/hsas/infrastructure/class_planner/` | Official timetable snapshot | Portal login flow change; timetable layout change; timetable not yet published for a term | 2026-10-27, snapshot captured (outcome not independently re-verified) |
| Notion | `src/hsas/infrastructure/notion/` | Workspace token, data sources, file upload, projection readback | Token scope or integration permissions; data-source property schema change; upload size limit; API rate limits; timestamp precision coarser than local state | 2026-10-27, review run |
| Apple Calendar and Reminders | `src/hsas/infrastructure/apple/` | Native EventKit bridge, macOS permissions, iCloud account | Denied or revoked native permissions; no signed-in iCloud account; bridge hash drift after app update; duplicate-container writes | 2026-11-02, worker sync `complete`: 63/63 EventKit readback verified (50 events + 13 reminders); iCloud server delivery **not** verified |

## Deliberately unverified at the moment

Nothing in this table should be treated as currently working because it worked on the
date shown. Before any task depends on one of these systems, re-verify that row, or state
plainly in the deliverable which row you are relying on and when it was verified.

## Where the evidence goes

Private run artifacts (screenshots, raw snapshots, receipts) live in the runtime data
directory, not in this repository. This table records the conclusion and the date; the
evidence stays private.
