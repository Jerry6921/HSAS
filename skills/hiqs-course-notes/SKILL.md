---
name: hiqs-course-notes
description: Generate English university course learning and revision notes from HIQS lectures and past papers or quizzes, following english-course-notes requirements and publishing under the corresponding Notion course. Use for whole-course or chapter notes, resuming a set, or revising saved units; ordinary course-fact queries use hiqs-course-information.
---

# HIQS Course Notes

Read [references/teaching.md](references/teaching.md) completely before planning
or authoring notes. It contains the full `english-course-notes` requirements,
including language, course stages, conceptual solution phases, unit reasoning,
Notion publication and final quality checks. These are the notes requirements,
not optional teaching suggestions. The bundled copy preserves the complete
source body so distribution does not depend on a personal Skill installation.

Deliver manageable conceptual notes as custom HTML reading bodies embedded in
Notion. Keep course guides and topic indexes entirely native Notion, with colored
column groups, ordered page links and concise route descriptions. Follow the
HTML/native delivery contract in teaching.md section 7.
For physics and physics-based engineering notes, also read
[references/physics-relationships.md](references/physics-relationships.md):
it implements explicit quantity dependencies, formula connections and justified
paths from givens to targets. Follow teaching.md section 5 for original question
images and general-law-first, stepwise worked solutions. Internal checkpoints
support the learning sequence without fixing published page boundaries.

Produce the entire agreed set in one request, using internal batches of coherent
learning units. Questions inside notes are self-study prompts; completion does
not depend on the student answering them or saying “continue”.

Use the HIQS MCP interface for source inventory and checkpoint operations. When
it is unavailable, preserve any existing local work and report the connection
needed; do not claim a run or background generation started. No private skill
paths, new credentials or external AI service are required.

## Resolve and inventory

1. Use `get_status`, `get_information` and `list_materials` to resolve the exact course ID,
   term, current lectures, historical questions and available answers. Inspect
   course identity from source content, not filename alone. Ask one focused
   question only if unresolved course/term ambiguity changes scope. English is
   the default for titles, prose, tables, captions, questions and answers; honor
   an explicit language request and preserve source notation and proper names.
   Use the archived `course_id` from `list_materials`; canonical course IDs may
   differ from the archive/Moodle identifier.
2. Call `get_course_notes()` before creating a run. Resume the matching scope
   and language, or create a new run when sources changed. Call
   `create_course_notes(course_id, scope, language, confirmed=true)` after scope
   is resolved. Review OCR, external/unavailable resources and collector limits
   from status/source metadata. `scope` must describe the term/version and included years, or
   explicitly state unresolved availability. A notes request authorizes these
   local checkpoints. It does not authorize course-fact writes or unrelated sync.
3. Read `get_course_notes_schema` and
   [references/checkpoints.md](references/checkpoints.md) before saving. Review
   every source as included or excluded with a reason. Classify lecture,
   syllabus, paper, quiz, answer and supplement from contents. Record unknown
   years/roles explicitly until resolved. Duplicate hashes preserve each source
   identity; exclude a duplicate only after confirming its relationship.

## Make the explanations independently understandable

Apply these HIQS requirements alongside the bundled teaching standard. Before a
central concept enters a formula or argument, establish the concrete scenario,
the object it describes and the question it answers. Distinguish levels of
description (such as a whole system, one point and a component of one quantity)
and explain how their representations should be interpreted.

Name the relationship being used: identity/equivalent representation, component
decomposition, rate of change, geometric conversion, governing law, conservation
or imposed constraint. Explain what licenses the connection; an equation linking
quantities does not make them the same kind of quantity or parts of one another.
For physics, use the classification, arrow semantics and rotation contrast in
[references/physics-relationships.md](references/physics-relationships.md).

Develop a concept through scenario and object → classification → meaning and
direction → relationship type → derivation → controlled contrast → independent
reconstruction, adapting this progression to the discipline and prior knowledge.
First hold the scenario and viewpoint fixed while changing one meaningful
condition; after explaining what changes and what remains invariant, broaden to
structurally different examples. Keep the reasoning in the note body so that
readers can reconstruct it without relying on explanations supplied only in chat.

## Make the presentation easy to scan

- Use bullet lists where parallel distinctions, assumptions, applicability
  conditions or checks are easier to compare; use numbered lists when order
  matters. Give each item enough explanation to stand alone, and keep causal
  links and derivations in connected prose around the lists.
- Use selective highlighter/background emphasis for key definitions, decisive
  distinctions, model conditions and conclusions. Include the essential qualifier
  in the emphasized text so a highlighted formula or claim stays accurate when
  skimmed. Keep most prose unhighlighted and express meaning in words as well as
  color; emphasis should reveal the learning structure.
- In HTML reading bodies, use styled semantic emphasis with readable contrast.
  In native Notion navigation or explicitly requested native supplements, use
  supported native background highlights. Use bold as the portable fallback. Keep definitions,
  reasoning and qualifications visible in the main text.

## Read and plan the whole set

4. Read each included source with `read_course_note_source`, starting at offset
   zero and following `next_offset` until `eof`. A search packet is useful for
   locating topics, never proof of full-course reading. The returned original
   paths are relative to `list_materials.resources_dir`; use the relevant PDF,
   slide or document tools to inspect diagrams, equations and scans. Complete
   text delivery is not visual completeness. Record exact failed pages and
   affected topics as reading limitations. If OCR changes inputs, start a new
   run and retain the prior checkpoint.
5. Apply the complete teaching requirements. Inspect relevant prior lessons,
   numbering, notation and the course-specific coverage ledger before continuing.
   Track covered, awaiting practice, unresolved confusion, deferred and outside
   scope separately; a generated note never proves mastery. Plan prerequisite-led
   conceptual units with stable IDs and explicit source relationships. Use
   syllabus topics such as Statics or Dynamics as groups, and coherent concepts
   or problem families as readable notes within each group. Preserve lecture
   order where sound; explain a teaching reason for reordering. Cover every
   major lecture concept even if no acquired question tests it. Unit boundaries
   follow coherent topics rather than file sizes or generation batch boundaries.
   For an existing run, preserve stable unit/artifact IDs and user-edited exports;
   map existing units to readable notes within topic groups and record the mapping
   in the publication receipt instead of silently renaming checkpoint identities.
6. Inventory each paper/quiz question with its verified year/version when
   available and locator (e.g. Q2(b)). Map it to units; retain historical-only
   and unmatched questions with explanations. Distinguish official answers with
   their own source locators from Agent derivations, teaching variants and
   unresolved answers. A historical question cannot silently expand the current
   syllabus. Sample frequency describes only the obtained sample.

## Author, checkpoint and finish

7. Save the plan and source reviews, then author every planned unit, overview,
   question map, rapid review and coverage/limitations report. Each artifact
   needs real source IDs and verified locators plus nearby citations in its
   prose. Link between notes with `<artifact_id>.md` (e.g. `models.md`), and
   return to `index.md`; the generated export index
   supplies the unified entry point. Avoid fabricated attachment links or page
   numbers. Explain missing papers/answers rather than inventing them. Include
   chapter consolidation with mixed model-selection and transfer problems before
   compressing the material into the rapid review. In this whole-set learning
   and revision workflow, the requested set includes that separate rapid review.
   Build each unit with connected explanations, quantity relationships,
   condition-labelled formula derivations and worked quantity paths. Keep each
   acquired question's uploaded original image beside its complete statement.
   Start solutions with the previously taught abstract law, identify this
   problem's terms, then explain successive expansions and constraints before
   numerical substitution. Save after meaningful internal batches; choose
   published reading-page boundaries by conceptual coherence and readability.
8. Call `save_course_notes` after each meaningful internal batch using the
   latest `revision`. It merges artifacts and reviews, preserving omitted ones.
   Fetch and reconcile after a stale-revision error. A retry resumes saved unit
   IDs; it does not create another run for the same unchanged task. On an actual
   interruption, save `partial`/`blocked` with `status_note` listing what remains.
   Checkpoints do not schedule background work.
9. Before requesting `complete`, compare every source and question to the
   planned and saved output. Confirm later units, prerequisite continuity,
   formula conditions, answer provenance, navigation and the final section.
   Also review whether the notes alone let a reader identify each central
   concept's object, meaning/representation, relationship type, conditions and
   changed-condition reasoning. Supply any missing explanatory bridge before
   treating authoring as finished; definitions, formulas and example counts alone
   do not establish this. This is an artifact review, not a requirement to wait
   for student answers or a claim that the student has mastered the material.
   Save `complete` only when `completion_blockers` is empty. A blocked scan or
   missing required material means `partial`, even if readable notes are useful.
   Source reading is Agent-attested; CORE validates the records, references and
   structural completeness, not teaching quality or student mastery.
10. Read back each artifact with `get_course_notes(run_id, artifact_id)` and
    inspect its exported Markdown, then complete the Notion delivery below.
    Verify list nesting and emphasis in the delivered HTML/native form; retain
    the conditions and explanations that give emphasized statements meaning.
    Deliver the verified Notion page links with a short description of coverage.
    When publication is blocked, provide the local index and concrete remaining
    publication issue. Report `content_status`, local delivery and publication
    separately. `mastery=not_assessed` stays unchanged by content generation.

## Destination and later revisions

Notion is the default destination, as required by `english-course-notes`, unless
the user explicitly selects another destination. A notes-generation request
authorizes publication under one verified corresponding course parent without
another routine confirmation. Resolve a new parent when switching courses;
preserve the accepted parent within its identified course. Use the available
Notion connector and the delivery workflow in `hiqs-notion-workspace`.

Follow the complete publication requirements in teaching.md section 7: discover
the connection, read the current enhanced-Markdown specification before authoring,
fetch the parent and prior notes, preserve lesson numbering and student content,
create topic notes or make targeted additions/corrections, then fetch every result.
Verify equations, tables, toggle nesting, sources, navigation and the final
section. Follow teaching.md section 2's manageable reading-note boundaries:
group notes of the same topic in native Notion columns with a consistent topic
background color and English label. Keep topic landing pages short, with an
ordered reading route and previous/next links in the reading notes. For each
HTML reading title in the native index, use the verified Notion page URL with its
HTML embed block anchor, following `hiqs-notion-workspace`; avoid temporary file
URLs. Existing pure native notes keep their format unless conversion is requested. During a
split, preserve and read back the destination content before replacing a long
body with navigation; keep source/question figures, interactive attachments,
student edits and child pages. Record artifact IDs → reading-note URLs → topic
group and concept headings in the publication receipt. Verify native column nesting,
colors, child pages and working links, plus each HTML embed, original figures
and rendered equations. Use HTML section anchors for reading-body contents;
reserve native tables of contents for native navigation headings. Rewrite local Markdown
navigation to actual Notion page links/mentions
when publishing; local filenames are not Notion links.

If the target remains ambiguous, prepare content and ask one destination question
before writing there. If publishing is unavailable, keep the local checkpoint and
draft, record pending/failed publication, and report the limitation. Record links
and readback evidence only after actual external verification. A locally complete
set is not a completed default Notion delivery. The canonical Notion projection
and `sync_notion` do not publish note prose.

For a correction, fetch the checkpoint and the exported file before changing the
affected unit and its review/question references. Preserve user edits. Exports
are saved per revision: the service detects and preserves edited files. Reconcile
the user's text into the submitted artifact and supply its edited-file hash in
`reconciled_exports`, preserving the old path.
New quizzes or changed source hashes require a new scoped run in this version;
reuse unaffected content only after checking its sources. Automatic incremental
invalidation across runs is deferred.
