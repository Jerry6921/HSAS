# ADR 0002 — A read-only local viewer, under a hard budget

- Status: accepted
- Date: 2026-11-02
- Supersedes nothing; it constrains the surface removed in `a2126e5`.

## Context

The local React dashboard, its HTTP server, the macOS shell and the DMG packaging were
removed because no Skill or agent workflow used them and they cost 14k lines, a pnpm
toolchain, 159 MB of `node_modules` and 33 browser-level tests.

Real use then showed the gap. Reading the system daily means two questions the terminal
answers badly:

1. **How old is what I am looking at?** The data store held timestamps but no judgement;
   "updated at 2026-10-27" does not tell a reader that this is six days old, or that
   Moodle's threshold is three.
2. **Where is that file?** Materials are 477 local documents behind a long relative path.
   Copying the path out of a JSON payload is the wrong workflow for "open the lecture note
   I half-remember".

Neither question needs a client framework. Both need a page.

## Decision

Keep a local viewer at `src/hsas/viewer/`, under constraints that make it unable to grow
back into the thing that was deleted:

- **Standard library only.** `http.server`, no dependency, no build step, no bundler, no
  `node_modules`. A change to the viewer is a Python edit and nothing else.
- **Server-rendered HTML.** One document per page, escaped with `html.escape`. No
  client-side framework, no hydration, no JavaScript as a requirement.
- **Read-only.** There is no POST handler, no form, no mutation route. It never writes
  course facts, checkpoints or configuration.
- **Loopback only.** It binds `127.0.0.1` and refuses any other host by construction.
- **Three pages.** `/` (freshness and counts), `/courses` (the material tree),
  `/courses/<id>` (facts and materials). A fourth page needs a recorded reason.
- **Served files come from the material service**, which already whitelists paths inside
  the snapshot; the viewer never invents file access.

## Consequences

- The viewer is roughly 450 lines, has no upgrade treadmill, and cannot break the agent
  path because agents do not use it.
- Freshness becomes visible to a human in one place. This is the main reason it exists:
  a system you depend on must be able to say when it is stale, and saying it only to
  agents is not enough.
- If the viewer ever needs a build step, a write route, or a second framework to stay
  useful, the correct action is to delete it again — not to adopt the toolchain. The
  budget is the feature.
