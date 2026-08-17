# capability-profile-closure（中文阅读版）

英文执行合同：[`SKILL.md`](../../.cap/capabilities/skills/capability-profile-closure/SKILL.md)

> 本文件是英文 Skill 的中文阅读版，不是运行时输入，也不是第二份执行合同。两者不一致时，以英文 `SKILL.md` 为准。

## 何时使用

当任务是创建、修改或审计 `.cap/manifest.toml`、`.cap/profiles/*.toml`、prompt、Skill、MCP、Hook 或 Plugin 时使用。

## 流程

1. 从当前任务确定项目根目录，然后要求项目同时存在 `AGENTS.md` 和 `.cap/manifest.toml`。缺少任一文件时先警告；只能在用户请求的范围内继续，不能从用户目录补齐。
2. 检查声明闭包：
   - manifest 列出所有可选择 profile，并且只指向项目内 profile；
   - 每个 profile 有一个 prompt 路径，并显式声明 `skills`、`mcps`、`hooks`、`plugins` 数组；
   - 每个被引用的 capability 都存在于 `.cap/capabilities/<kind>/`；
   - 每个已经存在的 capability，要么被引用，要么明确报告为有意未使用。
3. 检查路径卫生：id 使用小写连字符；路径是 `.cap/...` 下的 POSIX 相对路径；没有 symlink 依赖；没有写入用户级或 provider 原生全局根；没有 secret 文件。
4. 在所有结论中区分三种状态：
   - 声明态：manifest/profile/prompt/capability 文件；
   - 配置态：lock、render tree、materialized client config；
   - 生效态：真实客户端 run/probe 输出。
5. 优先执行只读检查：`cap agents`、`cap show <profile>`、`cap verify`，或底层 profile 工具的 `list/explain/verify`。只有在有意修改声明后才使用 `cap lock`。
6. 把 stale lock、未知效果、opaque Hook/Plugin staging 或客户端观测限制报告为风险，不能把它们转换成成功。

## 完成条件

选中的 profile 在有意修改后通过 lock/verify，所有声明的 capability 都是项目内的，并且交付说明检查了哪些状态层。
