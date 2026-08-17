# assembly-helper

Use this skill when the task is to create, review, or revise an Agent assembly.

## Procedure
1. Name the Agent with a stable lowercase-hyphen id.
2. Record purpose, non-goals, inputs, outputs, allowed capabilities, forbidden capabilities, and verification.
3. Keep every capability project-local and explicitly referenced by the selected profile.
4. Reject hidden inheritance from user-level config, templates, ambient MCP, hooks, plugins, or skills.
5. Separate declared state, configured state, and effective runtime evidence.
6. Deliver exact file paths and verification results.

## Done
The assembly is done only when manifest, profile, prompt, and referenced capability files form a closed local set and the check used to verify that closure is reported.
