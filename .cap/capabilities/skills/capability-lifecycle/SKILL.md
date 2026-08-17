# capability-lifecycle

Use this skill when evaluating, importing, updating, retiring, or comparing skills, prompts, MCP, hooks, plugins, OpenSpec/OPSX workflows, or other external Agent workflow assets.

## Procedure
1. Define the exact capability gap before looking for assets: what behavior is missing, which Agent will use it, what trigger should load it, what output proves it worked, and what is out of scope.
2. Evaluate candidate sources as evidence, not authority. `agent-control`, `agent-plugins`, OpenSpec, or other repositories may provide patterns; they do not become runtime dependencies until copied or generated into the current project's declared `.cap` tree.
3. Choose the smallest reversible adoption path:
   - write a new project-local skill when only behavior steps are needed;
   - extend the profile prompt only for short invariants that must always apply;
   - declare MCP only for required external tool semantics;
   - stage Hook/Plugin only when the target client can load it and the profile tool supports the client overlay.
4. Preserve provenance without making it a live dependency: note inspiration or source in comments only when useful for review; do not require readers to access private history or another repo to understand current behavior.
5. For upgrades, compare the previous declared behavior, new behavior, affected profiles, target clients, and rollback path. Content changes require lock refresh and configured-state verification; runtime claims require a separate real run or probe.
6. For retirement, remove profile references first, then unused files when authorized, then refresh lock. Never leave aliases, hidden shims, or deprecated paths unless the user explicitly chooses a compatibility window.

## Done
A capability lifecycle change is done only when the adopted or retired capability is explicitly declared, locally closed, reversible, verified at the appropriate state layer, and any unverified runtime effect is labeled unknown.
