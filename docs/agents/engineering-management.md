# Engineering management

HIQS is maintained by one person working with AI agents. Managing it is **boundary
management, not headcount management**: the cost is set by the number of external
contracts and their failure modes, not by line count. Every rule below exists to keep
that boundary visible and cheap to verify.

Snapshot used to set these rules (measured 2026-11-02): ~23k lines in `src/hsas/`,
365 tests running offline in ~30s (78% statement coverage), `contracts/` gated by CI,
four product Skills, a 57-tool MCP surface, and six external systems. Most complexity
sits in the adapters under `src/hsas/infrastructure/`, not in the domain model.

## Rules

### 1. One piece of work in flight

- At most one unmerged feature branch, and no unexplained modifications in the working
  tree. Land it or abandon it before starting anything else.
- "The suite is green" only means something on a committed tree. Uncommitted changes
  make every later failure ambiguous: the cause could be the environment, the edit, or
  the unlanded work.
- A new file under `tests/` is work in progress, not scratch. It is either completed and
  landed, or deleted.

### 2. Contracts before code

- `contracts/` is the single machine-checkable API surface for MCP and CLI. Change the
  schema first, regenerate, then implement against it.
- Never hand-edit generated files. `python scripts/generate_agent_contracts.py` plus
  `git diff --exit-code -- contracts` and `python scripts/check_generated.py` must stay
  clean; CI already enforces both.
- A new MCP tool needs a schema entry in the same change. If a tool cannot be described
  in the contract, the tool is not designed yet.

### 3. Keep the integration truth table

- `docs/integrations.md` is the only place that records whether an external system
  currently works. Keep it current whenever a collector is exercised or breaks.
- A row without a verified date is an assumption, not a fact. Never fill one from
  memory, from documentation, or from what an agent believes it observed.
- Verification means one real authenticated run. A test double, a mock, and a green
  unit test do not verify a live integration.

### 4. Freeze the compatibility layer

- `ui/`, `src/hsas/web/`, and `packaging/` accept crash fixes and security fixes only.
- New capability goes to Skills, services, and MCP. Do not add features to the legacy
  client, and do not let it absorb development time that belongs to the product surface.
- `ARCHITECTURE.md`'s "limited compatibility" section is the policy; this rule is its
  operational form.

### 5. Protect the offline, fast suite

- `python -m pytest` must stay fully offline and under roughly 60 seconds.
- Anything that needs network, login, MFA, a browser session, an installed app, or a
  real account is excluded from the default run and opted into explicitly.
- Do not add `sleep`-based coordination tests. A slow or flaky suite is deleted within a
  month, and with it the only cheap way to verify a change.

### 6. Private data lives outside the checkout

- Downloaded materials, extracted text, `information.json`, sync runs, exports and
  personal notes live in the runtime data directory, reached through the data-directory
  environment variable. `CONTRIBUTING.md` already states this rule.
- Never keep a second copy inside the checkout, not even gitignored. `.gitignore` only
  prevents a commit; it does not prevent deletion, accidental sync, or an agent reading
  stale state as current.
- Rationale: a checkout carrying hundreds of megabytes of private artifacts makes every
  file discovery and content search noisy, and makes "what is the real state" ambiguous.

### 7. Generate documentation, or write an ADR

- Anything mechanically derivable — module tree, contract list, CLI and MCP surface —
  belongs in a generated artifact gated by CI, not in prose.
- Anything that is a decision belongs in a short ADR under `docs/adr/`.
- Long hand-written prose that restates code is a liability: it drifts silently, and a
  drifted architecture document is worse than none because it is trusted.

### 8. Name things from the glossary

- `GLOSSARY.md` is the canonical vocabulary for domain terms in issues, proposals, tests
  and code. Create a term when a concept is first resolved; do not introduce synonyms.
- If a needed concept is absent, treat that as a design gap rather than inventing a name
  in one place.

### 9. Definition of done

A task is complete only when all of the following hold:

- [ ] `python -m ruff check src tests scripts` is clean.
- [ ] `python -m pytest` is clean, still offline, still fast.
- [ ] Contracts regenerated; `git diff --exit-code -- contracts` is clean.
- [ ] Generated UI and TypeScript contracts verified with `scripts/check_generated.py`.
- [ ] `docs/integrations.md` updated if any external system was exercised.
- [ ] No private runtime data added inside the checkout.
- [ ] Product Skills reinstalled via `scripts/install_agent_skills.py` **only when
      `skills/` content changed**; report the installer's report.
- [ ] The working tree contains no unexplained modification.

### 10. Explicitly out of scope

At this scale these are pure overhead and must not be adopted without a size change that
justifies them: microservices, splitting into multiple repositories, monorepo tooling,
mandatory code review, sprint and standup ceremony, and full domain-driven-design
ceremony. The project has one maintainer; a process that needs two people to run is a
process that will be skipped.
