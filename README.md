# agent-assembly

用于维护 **Agent 装配助手（assembly-helper）** 的项目内能力声明、提示词、Skills 与验证证据。

本仓库面向中文使用者：**说明文档以中文为主，运行时 Skill 正文保留英文**。这样既方便人阅读和审查，也避免把英文 Skill 的执行语义在翻译过程中改坏。

## 这个仓库解决什么问题

它不是通用 Plugin Marketplace，也不是用户级配置仓库。它只回答：

- 当前装配 Agent 是什么目标、边界和输出格式；
- 哪些 prompt / skills / MCP / hooks / plugins 被显式声明；
- 声明态、配置态和实际生效态分别有什么证据；
- 外部仓库的能力如何经过评估后，最小、可逆地进入项目闭包。

当前只有一个 profile：`assembly-helper`。

## 快速开始

从仓库根目录执行：

```bash
# 查看可用 Agent
python3 tools/cap.py agents

# 查看 profile 的能力闭包和三端 tree hash
python3 tools/cap.py show assembly-helper

# 校验 manifest、profile、prompt、Skills 与 lock
python3 tools/cap.py \
  --profile-tool ../agent-control/tools/profile/profile.py \
  verify
```

`../agent-control` 是本地相邻的参考仓。如果路径不同，使用显式参数替换：

```bash
python3 tools/cap.py \
  --profile-tool /path/to/agent-control/tools/profile/profile.py \
  verify
```

运行 OMP smoke test（需要外部认证库，不要把认证文件放进本仓）：

```bash
python3 tools/cap.py run assembly-helper --cli omp -- \
  -p "只输出：SKILLS-AVAILABLE: <skills>"
```

## 我应该先读什么

| 目的 | 入口 |
|---|---|
| 了解仓库边界 | [`AGENTS.md`](AGENTS.md) |
| 了解当前 Agent | [`.cap/prompts/assembly-helper.md`](.cap/prompts/assembly-helper.md) |
| 看中文 Skill 目录 | [`docs/skill-catalog.zh-CN.md`](docs/skill-catalog.zh-CN.md) |
| 了解如何修改和验收 | [`docs/maintenance.zh-CN.md`](docs/maintenance.zh-CN.md) |
| 查看机器可核验闭包 | [`.cap/lock.json`](.cap/lock.json) |
| 查看 profile 索引 | [`.cap/manifest.toml`](.cap/manifest.toml) |

## Skill 目录

运行时文件位于 `.cap/capabilities/skills/<name>/SKILL.md`，正文保持英文；中文概览见 [`docs/skill-catalog.zh-CN.md`](docs/skill-catalog.zh-CN.md)。

| Skill | 用途 |
|---|---|
| `assembly-helper` | 装配 Agent 的总入口：目标、边界、能力闭包和交付证据 |
| `agent-prompt-design` | 判断内容应进入常驻 prompt、条件 Skill、知识还是任务状态 |
| `capability-profile-closure` | 检查 manifest/profile/能力文件的本地闭包和三态证据 |
| `capability-lifecycle` | 评估、引入、升级、退役外部能力 |
| `spec-change-pack` | 用 OpenSpec/OPSX 的轻量思想组织较大的行为变更 |

## 三态语义

不要把“文件存在”当成“Agent 已生效”：

1. **声明态（declared）**：manifest、profile、prompt、Skill 文件。
2. **配置态（configured）**：lock、render tree、materialized client config、`probe` 结果。
3. **生效态（effective）**：真实客户端运行时的可观察输出。

Hook / Plugin 当前按 `opaque-staging` 处理；没有真实端加载证据时必须保持未知。本仓目前不声明 MCP、Hook 或 Plugin。

## 外部来源策略

`agent-control`、`agent-plugins`、OpenSpec 以及其他仓库只提供可审查的模式和证据，不自动成为本仓运行时依赖。需要引入时，先经过 `capability-lifecycle`，再把最小能力复制或生成到当前 `.cap` 目录，并更新 profile 和 lock。

## 仓库边界

- 本仓：装配助手的项目内 profile、prompt、Skills 和验证证据。
- `agent-control`：公共规则、profile 工具、schema、lock/render/probe 验证实现。
- `agent-plugins`：跨任务、跨客户端可安装的 runtime Skill / Plugin 资产。
- `open-spec`：本地参考克隆，不是本仓运行时依赖。

## License

MIT。见 [`LICENSE`](LICENSE)。
