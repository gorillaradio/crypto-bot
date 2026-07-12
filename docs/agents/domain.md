# Domain docs

How engineering skills consume this repo's domain documentation.

## Before exploring

Read, when present:

- `CONTEXT.md` at the repo root;
- `CONTEXT-MAP.md` instead, if it exists, following the contexts relevant to the task;
- ADRs under `docs/adr/` that touch the area being changed.

If these files do not exist, proceed silently. Domain-modeling workflows create them lazily when terms or decisions are resolved.

## Layout

This repo uses a single-context layout:

```text
/
├── CONTEXT.md
├── docs/adr/
└── ...
```

## Vocabulary and decisions

- Use domain terms as defined in `CONTEXT.md`; do not drift to avoided synonyms.
- If a needed concept is absent, reconsider the term or record the gap for domain modeling.
- Surface conflicts with an existing ADR explicitly instead of silently overriding it.
