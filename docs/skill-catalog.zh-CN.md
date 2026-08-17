# Skill 目录（中文说明）

每个运行时 Skill 都有两个入口：

- 英文 [`SKILL.md`](../.cap/capabilities/skills/)，是唯一执行合同；
- `docs/skills/<name>.zh-CN.md`，是对应的完整中文阅读版，只用于理解和审查。

中文阅读版不是运行时输入，也不是第二份执行合同。两者出现差异时，以英文 `SKILL.md` 为准；维护时应同步更新对应中文阅读版。

## 阅读顺序

1. 先读 [`assembly-helper` 中文版](skills/assembly-helper.zh-CN.md)，需要执行细节时对照[英文版](../.cap/capabilities/skills/assembly-helper/SKILL.md)。
2. 设计或修改提示词时读 [`agent-prompt-design 中文版`](skills/agent-prompt-design.zh-CN.md)。
3. 修改 `.cap` 声明或 lock 时读 [`capability-profile-closure 中文版`](skills/capability-profile-closure.zh-CN.md)。
4. 评估外部 Skill / Plugin / MCP / Hook 时读 [`capability-lifecycle 中文版`](skills/capability-lifecycle.zh-CN.md)。
5. 变更较大、需要审查和交接时读 [`spec-change-pack 中文版`](skills/spec-change-pack.zh-CN.md)。

## 1. assembly-helper · [中文全文](skills/assembly-helper.zh-CN.md) · [English](../.cap/capabilities/skills/assembly-helper/SKILL.md)

**何时使用**：创建、审查或修改 Agent 装配。

**它要求你记录**：

- 稳定的 Agent id；
- 目标和非目标；
- 触发条件；
- 输入和输出；
- 允许和禁止的能力；
- 验证方式；
- 剩余未知和风险。

**核心边界**：装配完成不等于客户端已经生效。必须区分声明态、配置态和生效态。

## 2. agent-prompt-design · [中文全文](skills/agent-prompt-design.zh-CN.md) · [English](../.cap/capabilities/skills/agent-prompt-design/SKILL.md)

**何时使用**：设计或修改系统提示词、profile prompt 或常驻 Agent 指令。

**关键判断**：

| 内容类型 | 应放在哪里 |
|---|---|
| 所有任务都必须遵守的短约束 | 常驻 prompt / 项目指令 |
| 有条件触发的多步骤流程 | Skill |
| 可复用的可信事实 | Knowledge |
| 当前任务进度、决定和临时状态 | Task state |

**不能做的事**：把长流程、任务状态、秘密或未经验证的运行态结论硬塞进常驻 prompt。

## 3. capability-profile-closure · [中文全文](skills/capability-profile-closure.zh-CN.md) · [English](../.cap/capabilities/skills/capability-profile-closure/SKILL.md)

**何时使用**：修改 `.cap/manifest.toml`、profile、prompt、Skills、MCP、Hook 或 Plugin。

**检查重点**：

- manifest 是否只指向项目内 profile；
- profile 是否显式声明 prompt、skills、mcps、hooks、plugins；
- 每个引用能力是否存在；
- 是否有未引用或隐式继承的能力；
- 是否存在 symlink、用户级能力旁路或 secret；
- lock 是否和当前声明一致。

**交付时必须说明**：检查覆盖了声明态、配置态还是生效态；未知不能写成成功。

## 4. capability-lifecycle · [中文全文](skills/capability-lifecycle.zh-CN.md) · [English](../.cap/capabilities/skills/capability-lifecycle/SKILL.md)
**何时使用**：评估、引入、升级、比较或退役外部 Agent 能力。

**工作原则**：

1. 先定义真实能力缺口，不先选仓库或平台。
2. 外部仓库是证据和模式来源，不是当前项目的授权源。
3. 优先选择最小、项目内、可回滚的能力。
4. 修改内容后必须刷新 lock 并检查配置态。
5. 只有真实运行或 probe 证据才可以支持生效态结论。
6. 退役时先从 profile 移除引用，再删除文件；不留隐式 alias 或 shim。

## 5. spec-change-pack · [中文全文](skills/spec-change-pack.zh-CN.md) · [English](../.cap/capabilities/skills/spec-change-pack/SKILL.md)
**何时使用**：新增 profile、改变 Agent 行为、跨客户端能力变更、风险迁移，或未来 Agent 需要审计的变更。

**借鉴 OpenSpec/OPSX 的部分**：

```text
proposal → behavior delta → design → tasks/evidence → archive
   why          what             how          prove           fold back
```

**重要限制**：

- 本仓没有被授权时，不自动创建 `openspec/`；
- planning 产物不等于 implementation 授权；
- `MODIFIED` 必须写完整的新行为，不能只写变更摘要；
- `REMOVED` 必须说明原因和迁移/回滚影响；
- 归档前必须有闭包验证和相称的运行证据。

## Skill 之间如何协作

```text
assembly-helper
    ├── agent-prompt-design
    ├── capability-lifecycle
    ├── capability-profile-closure
    └── spec-change-pack
```

这不是运行时状态机，而是阅读和选择顺序。具体任务只加载必要的 Skill，不为了“完整”把所有流程串起来。
