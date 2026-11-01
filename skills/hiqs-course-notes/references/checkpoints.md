# Checkpoint contract

Call `get_course_notes_schema` for current fields and enums. The tools delegate
to `HIQSPort`; this contract does not depend on a filesystem installation path.

`create_course_notes` returns `run_id`, `revision=0`, and source metadata with
hashes, duplicate relationships, extraction warnings and original paths. It
captures the entire archived course inventory; explicitly exclude irrelevant
sources. For missing external or undiscovered inputs, record the gap in
`limitations`; a local manifest alone cannot prove Moodle collection completeness.

`save_course_notes(run_id, expected_revision, update, confirmed=true)` accepts:

- `source_reviews`: upsert by `source_id`; role, disposition, reading state,
  verified locators, exclusion reason, limitations and question inventory status.
- `units`: when supplied, replace the ordered plan. IDs are lowercase slugs;
  `source_ids` identify inputs; prerequisites must refer to earlier unit IDs.
- `artifacts`: upsert by `artifact_id`; `kind`, title, complete Markdown `content`
  and `citations` containing `source_id` and `locator`. A unit artifact uses its
  unit ID. Other kinds are `overview`, `question-map`, `review`, `coverage`.
  The artifact ID `index` is reserved for generated navigation.
- `questions`: when supplied, replace the full question inventory. Keep stable
  question IDs, source/locator, unit IDs, scope and answer provenance. Mark
  `question_inventory_complete` only after reviewing every question in that
  source; a source with no actual questions needs an explanation in `reason`.
- `limitations`: when supplied, replace the run-level gaps. Keep missing inputs,
  conflicts affecting explanation, and unreadable locations explicit.
- `publication`: optional external destination, status, URL and readback note.
  `verified` is the Agent's attestation of external readback. Local readback is
  performed by CORE and reported independently as `local_delivery`.
  The field is optional for intermediate/local checkpoints; the Skill's default
  deliverable is Notion. Record pending/failed publication when it is blocked and
  never treat `content_status=complete` as external delivery success.
- `reconciled_exports`: only when a current exported note was edited, map its
  artifact ID to the SHA-256 of the actual edited file. Read and merge that text
  into a submitted replacement. Saving any batch refuses unreconciled edits,
  including edits to otherwise untouched units.
- `status`: `working`, `partial`, `blocked`, `complete`; partial/blocked requires
  a `status_note`. Completion never records student mastery.

Example of a first checkpoint after reading (IDs/locators must come from the
actual run; this is a structural example, not an ENGG1000 chapter plan):

```json
{
  "source_reviews": [{
    "source_id": "file-<returned-id>", "role": "lecture",
    "reading": "read", "locators": ["Slides 1–18"],
    "reason": "Inspected all extracted text and original diagrams"
  }],
  "units": [{
    "unit_id": "model-basics", "title": "Model basics",
    "source_ids": ["file-<returned-id>"], "prerequisites": []
  }],
  "status": "working"
}
```

On success, use the returned revision for the next batch. On failure, fetch the
checkpoint: validation/conflict fails before state replacement; export failure
can occur after a successful atomic checkpoint. `local_delivery.failed` means
content remains recoverable and `get_course_notes` can retry the projection.
Revision exports retain prior outputs and detect edits. Use `<artifact_id>.md`
for links within the bundle and `index.md` for its entry point. Every revision
contains the full saved set, so these links survive later batches. Complete
checkpoints reject Markdown links to absent note files.
