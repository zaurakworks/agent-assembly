# spec-change-pack

Use this skill when an Agent assembly change is large enough that reviewers need a durable change package, or when the project already uses OpenSpec/spec-driven change folders.

## Procedure
1. Decide whether the ceremony pays for itself. Use this skill for new profiles, changed Agent behavior, cross-client capability changes, risky migrations, or changes that future Agents must audit. Skip it for trivial text fixes.
2. Treat the change as one unit with one intent. If the proposal needs unrelated "and also" clauses, split it before implementation.
3. Package the unit as either the project's authorized OpenSpec change folder or, when OpenSpec is not authorized here, an equivalent issue/comment section. Do not create an `openspec/` tree or run `openspec init` unless the current project explicitly chose that workflow.
4. If the project does use OpenSpec, drive it through the CLI JSON surfaces rather than hand-built paths: `openspec status --json`, `openspec instructions <artifact> --json`, `openspec validate --json`, and archive/sync outputs are the controlling facts. Apply `context` and `rules` as prompt constraints, never copied file content.
5. Keep the four reviewable artifacts distinct:
   - proposal: why this Agent/capability change exists, one-sentence intent, scope, non-goals, affected profiles/capabilities, reversible boundary;
   - delta behavior: observable Agent behavior added, modified, removed, or renamed; include acceptance scenarios for trigger, output, refusal/exit, and state-layer claims;
   - design: capability source, prompt-vs-skill split, client differences, profile/lock/render implications, state-layer observability, no-secret boundary, rollback;
   - tasks/evidence: implementation checklist, checkbox-complete only when behavior is actually implemented, verification commands, observed outputs, remaining unknowns.
6. Keep deltas behavior-first. Requirements describe what a reviewer can observe from the Agent, not file names, implementation steps, or tool internals. Put implementation paths, profile commands, migration details, and line edits in design/tasks.
7. Use delta verbs deliberately:
   - ADDED for new behavior;
   - MODIFIED only with the full updated behavior, not a partial note;
   - REMOVED with reason and migration/rollback impact;
   - RENAMED only for naming changes without behavior change.
8. Separate planning from implementation. Creating a proposal/delta/design/tasks package authorizes planning evidence only; do not edit the actual profile/prompt/skill files until the current task also authorizes implementation.
9. After implementation, update the durable truth source: profile/prompt/skill files for this project. Archive or close the change package only after closure verification and, where claimed, runtime evidence exists.

## Done
The change package is done only when a reviewer can see intent, behavior delta, implementation plan, verification evidence, and archive/rollback state without relying on chat history.
