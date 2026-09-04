# HIQS information task guide

## 1. Mission

Answer course-information questions from the validated local database and
downloaded sources, or prepare a validated update. HIQS itself is not a study
planner. If a student asks for help thinking through a plan, ground the
conversation in retrieved course facts, keep suggestions distinct from facts,
and leave decisions with the student.

## 2. Facts to capture

For each course, capture when available:

- stable course ID, code, title, semester, instructors, links, policies;
- lectures, classes, tutorials, labs, office hours and their recurring times;
- assignments, quizzes, exams, presentations, projects and reports;
- open time, start time, exact DDL or date-only DDL, scheduled date and timezone;
- assessment format, submission method, requirements, word limit and GPA weight;
- location, relevant links, evidence, verification time, warnings and conflicts.

Unknown values stay unknown. A missing date never means that no deadline exists.

## 3. Query workflow

1. Run `hsas list-status` to locate resources and check material coverage.
2. Resolve the exact course and run `hsas query "QUESTION" --course COURSE_ID`.
3. Use structured matches for exact course facts and material excerpts for
   requirements or course content.
4. Answer the question directly with nearby source citations.
5. Name missing or tentative fields.
6. Cite the stored source title, page, path or URL when available.
7. Offer a data refresh only when the current source is stale or incomplete.

For time-sensitive questions, compare `last_verified_at`, source
`observed_at`, and the database `updated_at`. Do not call an old value current
without qualification.

## 4. Source-to-database workflow

1. Use `hsas sync-courses COURSE_ID` when the user asks to collect or refresh Moodle.
2. Export `hsas changes show --output pending-changes.json`.
3. For `full` mode inspect every listed file; for `incremental` mode inspect only listed changes and affected information items.
4. Prefer text sidecars for navigation, but open the source document when exact layout, tables, or wording matters.
5. Read PPTX slides and speaker notes, DOCX content, and relevant PDF pages.
6. Build a minimal `InformationUpdate` with complete records and stable IDs.
7. Apply it with `--changes pending-changes.json`, then verify the pending count decreased.
8. Follow [references/information-write-protocol.md](references/information-write-protocol.md).

## 5. Evidence authority

Use claim-specific authority:

```text
live Moodle activity metadata  → current open and due times
official syllabus/course file  → weight, format, requirements, policy
official timetable/announcement → class and tutorial changes
user-confirmed AI conversation → personal tutorial group or extra reminder
AI inference                   → never stored as a confirmed course fact
```

When sources conflict:

- retain both source references;
- use `date_status: tentative`;
- explain the conflict in `warnings`;
- do not silently select whichever date is easier.

## 6. Calendar timing

- Exact event: `starts_at` with optional `ends_at`.
- Exact deadline: `due_at`.
- Date-only deadline: `due_on`.
- Weekly class/tutorial: `recurrence`.
- Monday is weekday 0 and Sunday is weekday 6.
- Put holidays and reading weeks in `excluded_dates`.
- Put one-off make-up sessions in `additional_dates`.

If a tutorial time applies only to one group, identify the group in the title or
description. Never combine every available tutorial group into the student's
personal calendar unless the user asks for a full course timetable view.

## 7. Assessment display

When an item is clicked, the database should support:

- title, type and course;
- confirmed/tentative/unknown date status;
- open/start/end/due timing;
- format and submission method;
- weight and word limit;
- requirements and policies;
- source documents/pages or live links;
- warnings, conflicts and last verification time.

Do not add parent grading-group weights to all child weights unless the official
document says they are separate contributions.

The course overview uses `courses[].overview` and `courses[].objectives` for
official course-wide facts. Its visible assessment distribution is derived from
items with a confirmed `weight_percent`; missing weights remain missing rather
than being forced to total 100%.

## 8. User-provided extra information

A direct, unambiguous statement in the AI conversation confirms only the facts
it contains. The AI may prepare an incremental update for a selected tutorial,
temporary room change, teacher announcement, or reminder.

Do not infer unrelated preferences, private traits, or missing course facts.
Before applying, show any interpretation that could materially change the
calendar and use the normal validation plus `--confirmed` write path.

## 9. Missing and unreadable sources

| Condition | Required behavior |
|---|---|
| Download failed | Keep the previous file, report the failure, do not infer content |
| Google export requires access | Keep the external link and ask the user to grant access/open it |
| PDF is scanned | Mark OCR required and avoid unsupported claims |
| PPTX/DOCX has little text | Inspect images/layout with the relevant tool or report the limitation |
| Date missing | Keep the item under “date to verify” |
| Weight missing | Keep it null, never zero |
| Course reference unknown | Fix the course record before applying |
| Source conflict | Mark tentative, retain evidence and warning |

## 10. Response contracts

### Course schedule

```markdown
| Course | Type | Day/time | Effective dates | Location | Status/source |
```

### Deadline digest

```markdown
| Course | Assessment | Due | Weight | Format | Status/source |
```

No priority column is included by default. In a student-led planning
conversation, explain any user-chosen sorting rule and do not present it as an
official property of the course.

### Assessment detail

```markdown
## Assessment
- Timing
- Format and submission
- Weight and word limit
- Requirements and policies
- Evidence
- Unknown or conflicting fields
```

## 11. Quality checklist

- Correct course and stable IDs used.
- `moodle_course_id` links each AI course record to its local Moodle archive when the IDs differ.
- Every local file considered, including unassigned Moodle activities.
- PPTX speaker notes and DOCX text sidecars checked when relevant.
- Important dates, weights and requirements have evidence.
- Missing values stayed missing.
- Conflicts stayed visible.
- Update validated before write.
- Canonical `information.json` was not edited directly.
- No secret or authentication material was stored.
- Final answer leads with the requested fact, not a study recommendation.
