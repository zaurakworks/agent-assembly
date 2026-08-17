# assembly-helper（中文阅读版）

英文执行合同：[`SKILL.md`](../../.cap/capabilities/skills/assembly-helper/SKILL.md)

> 本文件是英文 Skill 的中文阅读版，不是运行时输入，也不是第二份执行合同。两者不一致时，以英文 `SKILL.md` 为准。

## 何时使用

当任务是创建、审查或修改一个 Agent 装配时使用。

## 流程

1. 为 Agent 取一个稳定的小写连字符 id。
2. 记录以下内容：目标、非目标、触发条件、输入、输出、允许的能力、禁止的能力和验证方式。
3. 使用 `agent-prompt-design`，把常驻 prompt 内容与条件性 Skill 流程、可复用知识分开。
4. 在采用外部 Skill、Plugin、MCP、Hook、OpenSpec workflow 或其他仓库的模式前，使用 `capability-lifecycle`。
5. 所有运行时能力必须是项目内的，并且必须由选中的 profile 显式引用。
6. 拒绝用户级配置、模板、ambient MCP、Hook、Plugin、Skill 或 marketplace 的隐藏继承。
7. 使用 `capability-profile-closure`，区分声明态、配置态和实际运行证据。
8. 对需要审查的非简单 Agent 行为变更，使用 `spec-change-pack`。
9. 交付精确文件路径、profile inventory、验证结果和剩余未知。

## 完成条件

只有当 manifest、profile、prompt 和被引用的 capability 构成闭合的本地集合，并且已经报告用于验证闭包的检查时，装配才算完成。
