# HIQS information task guide

## 1. Mission

Answer course-information questions from the validated local database and
downloaded sources, or prepare a validated update. Students retain ownership of
study planning. If a student asks for help thinking through a plan, ground the
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

Pending values stay pending. An absent date keeps the deadline status open for verification.

## 3. Query workflow

1. Run `hsas list-status` to locate resources and check material coverage.
2. Resolve the exact course and run `hsas query "QUESTION" --course COURSE_ID`.
3. Use structured matches for exact course facts and material excerpts for
   requirements or course content.
4. Answer the question directly with nearby source citations.
5. Name pending or tentative fields.
6. Cite the stored source title, page, path or URL when available.
7. Offer a data refresh only when the current source is stale or incomplete.

For time-sensitive questions, compare `last_verified_at`, source
`observed_at`, and the database `updated_at`. Label older values with their
verification date.

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
AI inference                   → suggestion or tentative interpretation
```

When sources conflict:

- retain both source references;
- use `date_status: tentative`;
- explain the conflict in `warnings`;
- explain the basis for any operational date selection.

## 6. Calendar timing

- Course teaching period: `courses[].starts_on` and `courses[].ends_on`.
- Exact event: `starts_at` with optional `ends_at`.
- Exact deadline: `due_at`.
- Date-only deadline: `due_on`.
- Weekly class/tutorial: `recurrence`.
- Monday is weekday 0 and Sunday is weekday 6.
- Put holidays and reading weeks in `excluded_dates`.
- Put one-off make-up sessions in `additional_dates`.

Use each item's `materials` array to connect the activity with the downloaded
slides, notes, tutorial sheets, exercises, readings, or assessment brief that
directly belongs to its week, topic, Moodle activity, or documented section.
Keep `sources` for evidence supporting the structured fact and `materials` for
resources the student can open while viewing the activity.

If a tutorial time applies only to one group, identify the group in the title or
description. Add the student's selected group to their personal calendar; use a
full course timetable view when the user requests every available group.

## 7. Assessment display

When an item is clicked, the database should support:

- title, type and course;
- confirmed/tentative/unknown date status;
- open/start/end/due timing;
- format and submission method;
- weight and word limit;
- requirements and policies;
- directly related learning materials;
- source documents/pages or live links;
- warnings, conflicts and last verification time.

Calculate parent and child grading-group totals according to the contribution
rules stated in the official document.

The course overview uses `courses[].overview` and `courses[].objectives` for
official course-wide facts. Its visible assessment distribution is derived from
items with a confirmed `weight_percent`; pending weights remain pending and the
visible total reflects confirmed entries.

## 8. User-provided extra information

A direct, unambiguous statement in the AI conversation confirms only the facts
it contains. The AI may prepare an incremental update for a selected tutorial,
temporary room change, teacher announcement, or reminder.

Limit interpretation to the facts stated by the user and the cited course sources.
Before applying, show any interpretation that could materially change the
calendar and use the normal validation plus `--confirmed` write path.

## 9. Pending and format-limited sources

| Condition | Required behavior |
|---|---|
| Download failed | Keep the previous file, report the failure, and mark content as pending |
| Google export requires access | Keep the external link and ask the user to grant access/open it |
| PDF is scanned | Mark OCR required and ground claims after visual or OCR review |
| PPTX/DOCX has little text | Inspect images/layout with the relevant tool or report the limitation |
| Date pending | Keep the item under “date to verify” |
| Weight pending | Keep it `null` |
| Course reference pending | Fix the course record before applying |
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

The default table focuses on course facts. In a student-led planning
conversation, explain each user-chosen sorting rule as a personal planning rule.

### Assessment detail

```markdown
## Assessment
- Timing
- Format and submission
- Weight and word limit
- Requirements and policies
- Evidence
- Pending or conflicting fields
```

## 11. Quality checklist

- Correct course and stable IDs used.
- `moodle_course_id` links each AI course record to its local Moodle archive when the IDs differ.
- Every local file considered, including unassigned Moodle activities.
- PPTX speaker notes and DOCX text sidecars checked when relevant.
- Important dates, weights and requirements have evidence.
- Pending values retained their pending state.
- Conflicts stayed visible.
- Update validated before write.
- Canonical `information.json` was written through the validated CLI workflow.
- Secret and authentication material remained inside the authentication boundary.
- Final answer leads with the requested fact; study suggestions appear in their own section.
