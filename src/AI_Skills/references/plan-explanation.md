# Plan generation and explanation

Read this reference when generating, comparing, or explaining `integrated_plan.json`.

## Ownership and provenance

The deterministic Planner owns the Plan. The AI may read and explain it, but must change only confirmed input data and then run `hsas update-plan`.

For a causal explanation, inspect:

- `source_snapshot.course_archives` and its collection timestamps;
- each `PlanItem.official_timing`, `academic_impact`, `learning_demand`, `effort`, `priority`, `readiness`, and `warnings`;
- `priority.derived_from` and rationale;
- `capacity_summary` and unscheduled workload;
- `feedback_summary` and execution calibration;
- course `changes/latest.json` for changed DDL, weights, activities, or materials;
- previous and current Plan when the user asks what changed.

Do not attribute a priority change to AI preference when the Planner records a course, profile, capacity, or feedback cause.

## Milestone model

`PlanItem.source_assessment_type` retains the normalized Assessment type that selects the strategy. Each `Milestone` contains:

- `milestone_id`: stable phase identity;
- `plan_item_id`: owning task;
- `phase`: machine-readable stage;
- `sequence` and `total_stages`: stage order;
- `target_at`: internal target before the official deadline buffer;
- `status`: planned, completed, or missed;
- `is_ai_created`: distinguishes internal planning dates from official facts.

Current deterministic strategies are:

| Assessment type | Stages |
|---|---|
| Essay, report, argument analysis, news report | requirements → research/outline → first draft → revision → submission ready |
| Exam or test | diagnostic → coverage → targeted practice → mock exam → final review |
| Project | scope → prototype → core build → integration/testing → delivery ready |
| Presentation | message/outline → draft materials → rehearsal → delivery ready |
| Other dated assessment | one ready milestone |

Milestones are recommendations. `official_timing` is the source-backed date and must remain visibly distinct. Completed milestones are preserved across refreshes; future targets are regenerated deterministically from the stable item creation/opening anchor and current official timing.

No deadline means no fabricated dated milestone. A `TBD` requirement remains a verification risk even when the assessment weight is confirmed.

## Explain a plan change as a causal chain

Use this compact order:

1. **Source change:** what changed in Moodle, syllabus, Profile, or Execution Log?
2. **Planner effect:** which urgency, impact, difficulty, effort, readiness, or capacity input changed?
3. **Plan effect:** which priority, milestone, time block, or warning changed?
4. **Student effect:** what should the student do now?

Example shape:

```text
Source change: Moodle now schedules Part I Test for 2 October.
Planner effect: The exam gained a confirmed deadline and urgency increased.
Plan effect: Five exam-preparation milestones were generated before the buffer.
Student effect: Begin the diagnostic stage this week; no official date was changed.
```

## Explanation rules

- Lead with the current next action or material change.
- Cite the strongest source and collection time for official facts.
- Say “the Planner derived” for priority, effort, and internal targets.
- Separate measured workload from default estimates and feedback-calibrated estimates.
- Name unscheduled minutes and the limiting availability when capacity is exceeded.
- If Profile availability is absent, explain why items exist but timetable blocks do not.
- If course data is stale or a sync failed, disclose it before strong time-sensitive advice.
- Avoid dumping raw JSON; show the smallest evidence needed to verify the explanation.
