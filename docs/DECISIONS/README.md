# Architectural Decision Records

This folder is the **memory of the project's decisions**. Read it before disagreeing with a choice — odds are someone already thought through it.

## Format

We use a lightweight ADR template:

```markdown
# ADR-NNNN: <Title>

**Status:** Proposed | Accepted | Superseded by ADR-MMMM
**Date:** YYYY-MM-DD
**Deciders:** <names>

## Context
What problem are we solving? What constraints?

## Decision
What did we decide?

## Consequences
Good and bad. Be honest about the bad.

## Alternatives considered
What did we look at and reject, and why?
```

## Rules

1. **Append-only.** To change a decision, write a new ADR that supersedes the old. Don't edit the old (other than updating its `Status` line).
2. **One decision per file.** Bundles get unwieldy.
3. **Numbered strictly.** No gaps, no reuse.
4. **Status must be honest.** `Proposed` until someone agrees. `Accepted` only after sign-off. `Superseded` includes a pointer to the new one.

## Index

| # | Title | Status |
|---|---|---|
| [0001](./ADR-0001-desktop-shell.md) | Desktop shell: Tauri + React | Accepted |
| [0002](./ADR-0002-gpu-backend-abstraction.md) | GPU backend abstraction: mock / remote / local | Accepted |
| [0003](./ADR-0003-initial-generator-choice.md) | Initial 3D generator: TripoSR (fast) + Hunyuan3D-2 (primary) | Accepted |
| [0004](./ADR-0004-python-runtime.md) | Python runtime: 3.10 via uv | Accepted |
| [0005](./ADR-0005-export-formats.md) | Export formats in v1: glb + obj + ply (fbx deferred) | Accepted |
| [0006](./ADR-0006-resumability-and-budget.md) | Resumability + budget-conscious operation as first-class | Accepted |
| 0007 | Texture-baking strategy | Proposed (TBD) |
| 0008 | Refinement strategy taxonomy | Proposed (TBD) |
| 0009 | Evaluator vision model choice | Proposed (TBD) |
