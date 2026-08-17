# Contributing to agent-assembly

感谢贡献。这个仓库维护的是项目内 Agent 装配声明，不是全局能力安装器。

## Scope

- Keep runtime capabilities under `.cap/capabilities/`.
- Reference every runtime capability from an explicit profile.
- Keep the English `SKILL.md` as the execution contract and put Chinese reading aids in `docs/`.
- Do not add secrets, credentials, personal runtime state, or user-level configuration.
- Do not introduce MCP, hooks, plugins, or external repositories as implicit dependencies.

## Change shape

For a non-trivial behavior change, include:

1. purpose and non-goals;
2. observable behavior delta;
3. prompt/skill/profile design;
4. verification and remaining unknowns.

Use the OpenSpec-inspired shape only when it pays for itself. Do not create an `openspec/` tree unless the project explicitly adopts that workflow.

## Checks

From the repository root:

```bash
python3 tools/cap.py \
  --profile-tool ../agent-control/tools/profile/profile.py \
  verify

git diff --check
```

If the selected profile changed, refresh the lock first:

```bash
python3 tools/cap.py \
  --profile-tool ../agent-control/tools/profile/profile.py \
  lock
```

Runtime claims require a focused client run or probe. A passing lock only proves the configured declaration is internally consistent.
