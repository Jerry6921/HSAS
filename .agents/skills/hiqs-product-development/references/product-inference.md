# Product inference

Use this guide when the request states the desired feature but leaves behavior,
failure handling, data ownership, or UI semantics unstated.

## Implement without asking

Infer and implement a choice when it is low-risk, reversible, consistent with
the current architecture, and necessary for a complete user outcome. Examples:

- a new asynchronous action needs progress, a terminal state, cancellation or a
  bounded retry path;
- a persisted model change needs backward-compatible defaults or migration;
- a UI list needs empty, loading, error, disabled, keyboard, and narrow-screen
  behavior appropriate to its existing component family;
- a mutation needs a visible result or audit summary;
- a derived cache or index needs automatic invalidation and recovery;
- generated frontend assets must be rebuilt after source changes;
- a repeated rule belongs in the owning service instead of being duplicated in
  adapters.

State important inferred behavior in the handoff, especially if it affects what
the user sees or where state is stored.

## Stop and ask

Ask when reasonable choices would produce materially different products, or the
choice would expand authorization. This includes:

- changing which system is authoritative for course facts;
- sending private course data to a new external service;
- publishing, pushing, releasing, messaging, purchasing, or deleting without a
  clear request;
- replacing a primary interaction model rather than extending it;
- destructive migration without a safe compatibility or recovery path;
- silently converting uncertain evidence into confirmed facts.

## Do not implement speculatively

Do not add adjacent features merely because they sound useful. Record them as
possible follow-ups when they are not required by the current outcome. Avoid
configurability that has no current user, abstractions with one hypothetical
caller, and permanent rules derived from a single screenshot or incident.

## Resolve ambiguity from evidence

Prefer, in order:

1. explicit user intent;
2. established project invariants and current product language;
3. existing behavior and tests;
4. the simplest reversible choice that completes the vertical slice.

When a request is corrected during implementation, remove the superseded model,
UI, prompt text, generated assets, and tests rather than layering a new option on
top of the abandoned design.
