# Agent Assembly

本仓库用于维护辅助装配 Agent 的项目内声明和能力面。中文导航见 `README.md`，每个 Skill 的中文全文见 `docs/skills/`；英文 `SKILL.md` 是执行合同。

## Repository rules

- 只使用本目录显式声明的 profile、prompt 和 capability；不得从用户目录、模板目录、其他项目或 provider ambient config 自动继承业务能力。
- Agent 装配采用显式能力面：`.cap/manifest.toml` 只索引可选择 profile，`.cap/profiles/*.toml` 声明 prompt 与能力闭包，`.cap/prompts/*.md` 保存运行提示词。
- 修改装配时同时更新声明、提示词、能力文件和可核验证据；不要把运行态、个人当前任务或 secret 写入本目录。
- 声明态、配置态和生效态必须分开报告；lock/verify 通过不等于客户端已加载，更不等于行为收益已证实。
- Skill 的英文正文是唯一执行合同；`docs/skills/*.zh-CN.md` 只用于中文阅读和审查，不创建第二份运行时合同。
- 首个 profile 是 `assembly-helper`，对应“辅助装配 Agent”。
- 维护流程和验证命令见 `docs/maintenance.zh-CN.md`。
