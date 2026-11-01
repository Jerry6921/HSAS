# Engineering management

HIQS is maintained by one person working with AI agents. Managing it is **boundary
management, not headcount management**: the cost is set by the number of external
contracts and their failure modes, not by line count. Every rule below exists to keep
that boundary visible and cheap to verify.

Snapshot used to set these rules (measured 2026-11-02): ~23k lines in `src/hsas/`,
400 tests running offline in ~7s (78% statement coverage; the native Swift
test is marked slow and opt-in), `contracts/` gated by CI,
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
  `git diff --exit-code -- contracts` must stay clean; CI enforces it, and
  `scripts/check_all.py` compares both snapshots in memory before committing.
- A new MCP tool needs a schema entry in the same change. If a tool cannot be described
  in the contract, the tool is not designed yet.

### 3. Keep the integration truth table

- `docs/integrations.md` is the only place that records whether an external system
  currently works. Keep it current whenever a collector is exercised or breaks.
- A row without a verified date is an assumption, not a fact. Never fill one from
  memory, from documentation, or from what an agent believes it observed.
- Verification means one real authenticated run. A test double, a mock, and a green
  unit test do not verify a live integration.

### 4. Do not resurrect a removed surface

- The local React dashboard, `hsas ui`, the macOS shell and the DMG packaging were
  removed because no Skill or agent workflow used them. They stay removed.
- Re-introducing one needs a recorded decision (`docs/adr/`) naming the workflow that
  cannot be served by Skills, MCP, CLI or Notion. "It used to exist" is not a reason.
- Local capability enters through MCP and CLI only. A new display surface belongs in
  Notion, not in another in-repo client.

### 5. Protect the offline, fast suite

- `python -m pytest` must stay fully offline and under roughly 60 seconds. The default
  run already applies `-m 'not slow'` from `pyproject.toml`; keep it that way.
- Anything that needs network, login, MFA, a browser session, an installed app, or a real
  account is marked `@pytest.mark.slow` and opted into explicitly. Mark it — do not delete
  it, and never let it leak into the default run.
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

Run `python scripts/check_all.py` first. It is the single local gate: lint, every
committed contract snapshot (compared in memory, so it never rewrites files), and the
default test suite at the coverage threshold CI enforces (CI measures it on one
interpreter leg; every leg still runs the suite). `tests/test_gate_parity.py`
compares the script against `.github/workflows/quality.yml`, so the two cannot drift.

Three CI steps stay release-only and are not in the local gate: the dependency audit,
building the wheel, and verifying the wheel installs. They change only when dependencies
or packaging change, and they are slow and network-bound. A green `check_all` therefore
means "CI's lint, contract and test steps will pass", not "the release will publish"

A task is complete only when all of the following hold:

- [ ] `python scripts/check_all.py` is green.
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
