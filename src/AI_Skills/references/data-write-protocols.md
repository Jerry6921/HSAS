# Confirmed-data write protocols

Read this reference before changing `student_profile.json` or `execution_log.json`. These files are user-owned Planner inputs. CourseArchive and Integrated Plan are not AI-writable inputs.

## What counts as confirmation

A direct, unambiguous user statement confirms only the facts it contains; a second confirmation is unnecessary unless the proposed interpretation is ambiguous, destructive, or materially broader.

| User statement | Confirmed | Not confirmed |
|---|---|---|
| “I can study Wednesday 19:00–22:00.” | That Wednesday availability block | Preferred session length, energy level, or daily maximum |
| “It took me 90 minutes and I finished the planned block.” | Actual duration and completion of that block | Completion of the whole assessment unless explicitly stated |
| “I usually need longer for essays.” | A profile note or proposed preference | A numeric calibration factor |
| “Move everything to Saturday.” | Requested planning outcome | Replacement availability or cancellation of fixed commitments without clarification |

AI inference, a prior recommendation, Moodle completion metadata, and silence are not user confirmation. Never persist authentication data or sensitive traits inferred from behavior.

## Profile update transaction

1. Read and validate the existing file as `StudentProfile`.
2. Resolve the exact target field; ask only if the statement maps to multiple materially different fields.
3. Apply a minimal patch to a copy. Preserve all unrelated and unknown values.
4. Check duplicate course states, overlapping availability/commitments, timezone validity, and field bounds through Pydantic validation.
5. Set `updated_at` and `provenance.last_confirmed_at` to the write time. Set `provenance.confirmed_by_user=true` for a confirmed write and remove only the confirmed field paths from `unconfirmed_fields`.
6. Do not set `profile_status=active` merely because one field changed. Activate only when the Profile has enough confirmed availability and context for the requested planning mode.
7. Persist the validated model through the project's atomic `write_model`; do not partially rewrite JSON text.
8. Run `hsas update-plan`. If validation fails, keep the valid Profile input, retain the last known good Plan, and report the planner error.

Replacing or deleting existing availability, commitments, constraints, goals, or results requires clear scope. “Add” is not permission to replace, and a correction should update the identified value rather than append a contradictory duplicate.

## Execution record transaction

An execution record represents one real study event, not an estimate or AI recommendation.

Required facts:

- exact `plan_item_id` from the current plan;
- matching current `item_type`;
- event/record time;
- planned minutes from the referenced block or explicitly confirmed plan;
- user-confirmed actual minutes;
- user-confirmed equivalent planned progress, or an explicit whole-item completion statement.

`actual_minutes` measures clock time. `progress_minutes` measures how much of the planned work was completed. They are not automatically equal. If the user reports only time but not progress/completion, ask one concise question rather than relying on the schema's default.

For idempotency:

1. Create one stable ID per event, such as `execution:<plan_item_id>:<event-time-UTC>`. Preserve that proposed ID across retries in the same operation.
2. Before appending, check `record_id` and compare plan item, event time, and notes for an equivalent existing event.
3. A retry returns the existing record; it does not append another.
4. When the user corrects a known event, update that record after explicit correction instead of creating a second event. Note the correction when useful.
5. Deletion requires an explicit request identifying the event. Do not erase history merely because an estimate changed.

Validate the complete candidate `ExecutionLog`, update its `updated_at`, write atomically, then run `hsas update-plan`. If a referenced plan item no longer exists or its type changed, stop and resolve the current item instead of storing an orphan.

## Write-result response

After a successful mutation, tell the user:

- exactly which confirmed fields or execution event were recorded;
- whether the Planner and Validator succeeded;
- what priorities, capacity, or schedule changed materially;
- what remains unknown or requires confirmation.

Do not expose the full private Profile or unrelated execution history in the response.
