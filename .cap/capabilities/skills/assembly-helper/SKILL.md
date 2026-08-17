# assembly-helper

Use this skill when the task is to create, review, or revise an Agent assembly.

## Procedure
1. Name the Agent with a stable lowercase-hyphen id.
2. Record purpose, non-goals, trigger conditions, inputs, outputs, allowed capabilities, forbidden capabilities, and verification.
3. Use `agent-prompt-design` to split always-on prompt content from conditional skill workflows and reusable knowledge.
4. Use `capability-lifecycle` before adopting external skills, plugins, MCP, hooks, OpenSpec workflows, or patterns from another repository.
5. Keep every runtime capability project-local and explicitly referenced by the selected profile.
6. Reject hidden inheritance from user-level config, templates, ambient MCP, hooks, plugins, skills, or marketplaces.
7. Use `capability-profile-closure` to separate declared state, configured state, and effective runtime evidence.
8. Use `spec-change-pack` for non-trivial Agent behavior changes that need reviewable proposal/delta/design/evidence.
9. Deliver exact file paths, profile inventory, verification results, and remaining unknowns.

## Done
The assembly is done only when manifest, profile, prompt, and referenced capability files form a closed local set and the check used to verify that closure is reported.
