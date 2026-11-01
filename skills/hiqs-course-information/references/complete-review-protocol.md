# Complete file review, calendar and task delivery

Use for a full/incremental source review or a request to generate or reconcile
calendar and to-do entries. A completeness claim is bounded by the named courses,
semester, source snapshot and authorized files. Collection, reading, extraction,
canonical persistence and external delivery have separate completion states.

## 1. Freeze and inventory the scope

Export exact source batches and read the current canonical records. Record the
course IDs, term, source observation times and review mode. Call `list_materials`
for **every** linked Moodle archive, including `additional_moodle_course_ids`.
Inspect `activities`, `page_content`, `documents` and `coverage.gaps`, not only
downloaded files or search hits. `unassigned_activities`, inline Moodle dates,
tables, announcements and nested pages can contain obligations without a file.
Inspect SIS/Planner batches independently; this manifest covers Moodle only.

`inventory_ready` means no known acquisition gap was detected. It does not certify
reading, visual coverage, freshness at the institution, or semantic accuracy.
Retain failed/external/restricted/skipped activities, missing originals/sidecars,
OCR flags, blank units and crawl truncation in the review record. Repair relevant
gaps with authorized collection/OCR or format-aware original-file reading. A
source that remains inaccessible is an explicit limitation, not a reviewed file.
Re-export batches after a changed source snapshot; old readings do not cover new
bytes. An absent source is not evidence of cancellation or contradiction.

## 2. Read and record coverage in recoverable batches

Save a private run record under `<RESOURCES_DIR>/ai-state/information-review/`
when writable, or a task-local `work/information-review/<run_id>/coverage.json`
otherwise. This is an Agent-authored receipt, not canonical data or a service
attestation. Save after each manageable batch so a continuation can resume it.

For each source record:

- course/archive ID, stable evidence ID or activity ID, path/URL, snapshot time;
- original SHA-256 and text SHA-256 when available;
- total pages/slides/parts, ranges actually read and remaining ranges;
- status: `pending`, `read`, `blocked`, `excluded`, or `duplicate_of`;
- exclusion/blocker reason, visual/OCR checks and extracted claim/item IDs.

Full mode reads every authorized source in the exported scope. Incremental mode
reads changed content plus affected prior facts and their supporting evidence;
unchanged sources retain their prior versioned review. Read all returned chunks
or full source units, not just search excerpts, summaries, the first pages or
keyword hits. Preserve PDF page boundaries, slide notes, DOCX tables/footnotes,
and workbook sheet/cell locations using appropriate format readers. Inspect
original images/tables where layout carries meaning; OCR completion alone is
not a visual accuracy check. A file being classified is not evidence it was read.

Identical original hashes may share a reading only when the reviewed content and
extraction are the same; retain each course/activity's distinct context. A
renamed file with changed bytes requires fresh reading. Mark `read` only after
all relevant units are covered; `duplicate_of` must point to a reviewed version.

## 3. Reconcile claims into events and obligations

Build a source-to-item map. Each explicit obligation/date/requirement resolves
to a stable item ID, a source-backed correction of an existing ID, or a documented
exclusion. Include registration/group selection, required preparation, individual
milestones and ungraded compulsory work when the sources require them. Retain
source locators for each important field; use `sources[].note` to identify which
fields a source supports. A title or filename alone is not a usable locator.

- `task_role: action`: something the student must do, including `other` or
  undated readings. `reference`: an overview, rubric or parent assessment summary
  without a separate obligation. `auto` retains category-based legacy defaults.
- Record one task for each distinct deliverable. A parent overview is not a
  second submission; separately required components keep separate IDs.
- Unknown dates remain canonical obligations with `date_status: unknown`;
  they are excluded from Apple delivery until confirmed and dated. Record a
  date-only deadline as `due_on`; preserve exact times and timezone only when
  supported. Never substitute midnight, 23:59, a study target or a past year.
- Keep opening, meeting start/end and submission deadline in their own fields.
  Apple and ICS retain distinct milestones, including recurring items' deadlines.
- Check weekly bounds, weekday, group/section, exclusions, additions and specific
  cancellations/moves against current evidence. Do not merge alternative groups
  into a fictitious personal timetable or infer holiday cancellation unaided.
- Resolve changed/removed sources against retained evidence. Preserve an item
  until its correction/cancellation is justified; omission from an upsert is not
  deletion. Keep tentative and conflicting facts visible with their source basis.

## 4. Preflight and apply

Call `validate_information_update`. Validation now checks the merged store,
including preserved records, and returns `quality_audit` plus `ready_to_apply`.
Review every finding: fix inconsistent incoming dates; resolve duplicate
candidates by stable ID; supply missing provenance; retain unresolved real-world
unknowns with a specific limitation. Unknown dates are not validation failures.
`valid: true` confirms structural validity, not completeness or correct reading.

Compare the audit's actionable item IDs, undated task count and calendar
occurrence IDs with the source-to-item map. Every required deliverable must be
accounted for even if no date exists. Explain legitimate duplicate-looking
items rather than deleting them automatically. The service rejects inconsistent
incoming opening/deadline fields before any canonical write/checkpoint.

Apply only the authorized update. Attach only source batches whose exact scope
has been reviewed. For a partial review, save supported facts without acknowledging
unread batches; narrow/re-export a batch where supported rather than claiming the
whole queue. Zero-change acknowledgement requires the same reading coverage as
a changed batch. Save the returned summary and verify canonical readback.

## 5. Verify delivery and report the boundary

For authorized Apple sync, compare eligible confirmed, dated, unexpired tasks
and occurrences with the Apple projection and receipt. Reconcile every excluded
obligation with its reason; full canonical coverage does not mean every record
belongs in the agenda. Preserve completion state in Apple Reminders. Follow the
Apple sync protocol for local-day expiry, recurrence filtering and cloud limits.

For authorized Notion sync, require `scope: library`, course/material identities
and no task/calendar records. Read back projected course/archive properties and
material relations. Preserve note prose, attachments and user drafts. Do not
recreate an old to-do/calendar view to make counts match canonical obligations.
Require `verification.status: verified`, matching expected/matched counts, and
no write/relation/removal errors before calling metadata delivery verified.
Upload/attachment accessibility requires its own receipt; row verification does
not verify file bytes. Report oversized and failed uploads independently.

Finish with courses/snapshot covered; read/blocked/excluded/duplicate source
counts and remaining ranges; new/changed tasks and calendar counts; unknown dates,
conflicts and provenance gaps; canonical apply/checkpoint and publication results.
Claim full coverage only when every expected source and obligation has a recorded
disposition and every unresolved limitation is disclosed. Do not promise absolute
accuracy: a passed audit cannot prove that source authors or Agent interpretation
are error-free, nor predict future source changes.
