# spec-change-pack（中文阅读版）

英文执行合同：[`SKILL.md`](../../.cap/capabilities/skills/spec-change-pack/SKILL.md)

> 本文件是英文 Skill 的中文阅读版，不是运行时输入，也不是第二份执行合同。两者不一致时，以英文 `SKILL.md` 为准。

## 何时使用

当 Agent 装配变更足够大，需要可持久审查的变更包，或项目已经使用 OpenSpec/spec-driven change folder 时使用。

## 流程

1. 先判断流程成本是否值得。适用于新增 profile、改变 Agent 行为、跨客户端能力变更、风险迁移或未来 Agent 需要审计的变更；简单文字修正跳过。
2. 一个变更只保留一个意图。如果 proposal 需要多个无关的“另外还要”，先拆分。
3. 变更可以使用项目已授权的 OpenSpec change folder；如果 OpenSpec 尚未被当前项目授权，则使用等价的 Issue/comment 结构。没有明确选择时，不创建 `openspec/`，也不运行 `openspec init`。
4. 如果项目使用 OpenSpec，通过 CLI 的 JSON 接口获取事实，而不是手工猜路径：`openspec status --json`、`openspec instructions <artifact> --json`、`openspec validate --json` 以及 archive/sync 输出都是控制事实。`context` 和 `rules` 是 prompt 约束，不要原样复制进文件。
5. 保持四类审查产物分离：
   - proposal：为什么要改、单句意图、范围、非目标、受影响 profile/capability 和可逆边界；
   - behavior delta：可观察的新增、修改、删除或重命名行为；包括触发、输出、拒绝/退出和状态层结论的验收场景；
   - design：能力来源、prompt 与 Skill 的分工、客户端差异、profile/lock/render 影响、状态层观测、无 secret 边界和回滚；
   - tasks/evidence：实现清单、只有行为真正完成才勾选、验证命令、观测输出和剩余未知。
6. delta 以行为为中心。需求描述审查者可以观察到的 Agent 行为，不写文件名、实现步骤或工具内部细节。路径、profile 命令、迁移细节放入 design/tasks。
7. 有意识地使用 delta 动词：
   - `ADDED`：新行为；
   - `MODIFIED`：已有行为被修改，必须写完整的新行为，不能只写摘要；
   - `REMOVED`：行为被删除，必须说明原因和迁移/回滚影响；
   - `RENAMED`：只改名称，不改行为。
8. 分离 planning 和 implementation。创建 proposal/delta/design/tasks 只授权规划证据，不自动授权修改实际 profile/prompt/Skill；除非当前任务同时覆盖 implementation。
9. 实施后更新项目内的持久真相源：profile/prompt/Skill。只有闭包验证完成，并且在需要声称运行时效果时具备运行证据，才归档或关闭变更包。

## 完成条件

审查者无需依赖聊天历史，就能看到意图、行为差异、实施计划、验证证据和归档/回滚状态。
