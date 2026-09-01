# Confirmed-data write protocols

Read this reference before changing `student_profile.json` or `execution_log.json`. These files are user-owned Planner inputs. CourseArchive and Integrated Plan are not AI-writable inputs.

## What counts as confirmation

A direct, unambiguous user statement confirms only the facts it contains; a second confirmation is unnecessary unless the proposed interpretation is ambiguous, destructive, or materially broader.

| User statement | Confirmed | Not confirmed |
|---|---|---|
| “I can study Wednesday 19:00–22:00.” | That Wednesday availability block | Preferred session length, energy level, or daily maximum |
| “It took me 90 minutes and I finished the planned block.” | Actual duration and completion of that block | Completion of the whole assessment unless explicitly stated |
| “I usually need longer for essays.” | A profile note or proposed preference | A numeric calibration factor |
| “I will handle the urgent items on Saturday.” | Session-only intent unless the user asks to save it | Replacement availability or a timetable entry in Integrated Plan |

AI inference, a prior recommendation, Moodle completion metadata, and silence are not user confirmation. Never persist authentication data or sensitive traits inferred from behavior.

## Profile update transaction

1. Run `hsas profile validate`, then read only the Profile fields needed for the request.
2. Resolve the exact target field; ask only if the statement maps to multiple materially different fields.
3. Create a temporary JSON object containing only the confirmed fields. Preserve all unrelated and unknown values by omission.
4. Check duplicate course states, overlapping availability/commitments, timezone validity, and field bounds through Pydantic validation.
5. After confirmation, run `hsas profile apply <patch.json> --confirmed`. `ProfileService` deep-merges the patch, rejects authentication and system-managed fields, sets timestamps/provenance, validates the complete object, and writes atomically.
6. Do not set `profile_status=active` merely because one field changed. Activate only when the Profile has enough confirmed goals, preferences, constraints, or course context for personalized prioritization. Exact availability is not required.
7. The CLI automatically requests `hsas update-plan`. Verify its result; if validation fails, keep the valid Profile input, retain the last known good Plan, report the planner error, and treat Plan status as stale.

Replacing or deleting existing availability, commitments, constraints, goals, or results requires clear scope. “Add” is not permission to replace, and a correction should update the identified value rather than append a contradictory duplicate.

## Execution record transaction

An execution record represents one real study event, not an estimate or AI recommendation.

Required facts:

- exact `plan_item_id` from the current plan;
- matching current `item_type`;
- event/record time;
- approximate planned minutes from the AI-proposed learning action or an explicitly confirmed budget;
- user-confirmed actual minutes;
- user-confirmed equivalent planned progress, or an explicit whole-item completion statement.

`actual_minutes` measures clock time. `progress_minutes` measures how much of the planned work was completed. They are not automatically equal. If the user reports only time but not progress/completion, ask one concise question rather than relying on the schema's default.

For idempotency:

1. Create one stable ID per event, such as `execution:<plan_item_id>:<event-time-UTC>`. Preserve that proposed ID across retries in the same operation.
2. Run `hsas execution add <plan_item_id>` with the proposed `--planned-minutes` plus confirmed actual and progress minutes. Pass the stable `--record-id` when retry safety matters.
3. `ExecutionService` derives `item_type` from the current Plan, validates references, rejects conflicting duplicate IDs, validates the complete log, and writes atomically. An identical retry returns the existing record.
4. When the user corrects a known event, run `hsas execution correct <record_id>` after explicit correction instead of creating a second event.
5. Deletion requires an explicit request identifying the event and is not currently exposed by the CLI. Do not erase history merely because an estimate changed.

After a successful add/correction, verify the CLI's automatic replan. If it was deferred, run `hsas update-plan` explicitly. If a referenced plan item no longer exists or its type changed, stop and resolve the current item instead of storing an orphan. Never edit `execution_log.json` directly.

## Write-result response

After a successful mutation, tell the user:

- exactly which confirmed fields or execution event were recorded;
- whether the Planner and Validator succeeded;
- what priorities, effort estimates, or learning recommendations changed materially;
- what remains unknown or requires confirmation.

Do not expose the full private Profile or unrelated execution history in the response.
