# Agent Assembly

本目录用于维护辅助装配 Agent 的本地声明和能力面。

- 只使用本目录显式声明的 profile、prompt 和 capability；不得从用户目录、模板目录或其他项目自动继承业务能力。
- Agent 装配采用显式能力面：`.cap/manifest.toml` 只索引可选择 profile，`.cap/profiles/*.toml` 声明 prompt 与能力闭包，`.cap/prompts/*.md` 保存运行提示词。
- 修改装配时同时更新声明、提示词、能力文件和可核验证据；不要把运行态、个人当前任务或 secret 写入本目录。
- 首个 profile 是 `assembly-helper`，对应“辅助装配 Agent”。
