# capability-profile-closure

Use this skill when creating, modifying, or auditing `.cap/manifest.toml`, `.cap/profiles/*.toml`, prompts, skills, MCP, hooks, or plugins.

## Procedure
1. Locate the active project root from the current task, then require both project `AGENTS.md` and `.cap/manifest.toml`. If either is missing, warn and continue only within the user's requested scope; never backfill from a user directory.
2. Check declaration closure:
   - manifest names every selectable profile and only project-local profile paths;
   - each profile has one prompt path and explicit `skills`, `mcps`, `hooks`, and `plugins` arrays;
   - every referenced capability exists under `.cap/capabilities/<kind>/`;
   - every present capability is either referenced or intentionally unused and reported.
3. Check path hygiene: lowercase-hyphen ids, POSIX relative `.cap/...` paths, no symlink dependency, no overlay into user-level or provider-native global roots, no secret files.
4. Separate the three states in all claims:
   - declared state: manifest/profile/prompt/capability files;
   - configured state: lock, render tree, materialized client config;
   - effective state: observed client run/probe output.
5. Prefer read-only checks first: `cap agents`, `cap show <profile>`, `cap verify`, or the underlying profile tool's `list/explain/verify`. Use `cap lock` only after an intentional declaration change.
6. Report stale lock, unknown effect, opaque Hook/Plugin staging, or client-specific observability limits as risks instead of converting them to success.

## Done
Closure is done only when the selected profile passes lock/verify after intentional edits, all declared capability files are project-local, and the delivery names which state layers were checked.
