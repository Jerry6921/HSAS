# Domain Docs

HIQS uses a single-context domain documentation layout. These rules supplement the existing HIQS instructions in `AGENTS.md`.

## Before exploring

- Read `GLOSSARY.md` at the repository root when present.
- Read ADRs in `docs/adr/` that concern the area being explored.

If these files do not exist, proceed silently. The domain-modeling skill creates them lazily when terms or decisions are resolved.

## File structure

```text
/
├── GLOSSARY.md
├── docs/adr/
│   └── 0001-<decision>.md
└── src/
```

## Use the glossary's vocabulary

When naming a domain concept in an issue, proposal, hypothesis, or test, use the term defined in `GLOSSARY.md`. If the needed concept is absent, reconsider whether it belongs to the project or note the gap for domain-modeling.

## Surface ADR conflicts

If a proposal contradicts an existing ADR, identify the ADR and explain why its decision should be reconsidered.
