# capability-lifecycle（中文阅读版）

英文执行合同：[`SKILL.md`](../../.cap/capabilities/skills/capability-lifecycle/SKILL.md)

> 本文件是英文 Skill 的中文阅读版，不是运行时输入，也不是第二份执行合同。两者不一致时，以英文 `SKILL.md` 为准。

## 何时使用

当任务是评估、引入、升级、退役或比较 Skill、prompt、MCP、Hook、Plugin、OpenSpec/OPSX workflow 或其他外部 Agent workflow 资产时使用。

## 流程

1. 在查看候选资产前，先定义准确的能力缺口：缺什么行为、哪个 Agent 会使用、什么触发条件会加载、什么输出能证明成功，以及不做什么。
2. 把候选来源当作证据，不当作权威。`agent-control`、`agent-plugins`、OpenSpec 或其他仓库可以提供模式，但在复制或生成到当前项目的 `.cap` 树并完成声明前，不会成为运行时依赖。
3. 选择最小、可逆的采用路径：
   - 只需要行为步骤时，写一个新的项目内 Skill；
   - 只有必须始终生效的短不变量才进入 profile prompt；
   - 只有确实需要外部工具语义时才声明 MCP；
   - 只有目标客户端能够加载、且 profile 工具支持对应 overlay 时，才 staging Hook/Plugin。
4. 保留来源信息，但不要制造运行时依赖：只有有助于审查时才在注释中记录来源；不要要求读者访问私有历史或其他仓库才能理解当前行为。
5. 升级时比较旧的声明行为、新行为、受影响的 profile、目标客户端和回滚路径。内容变化必须刷新 lock 并验证配置态；运行时结论必须另做真实 run 或 probe。
6. 退役时先从 profile 移除引用，再在获得授权后删除不再使用的文件，然后刷新 lock。除非用户明确选择兼容窗口，否则不要留下 alias、隐藏 shim 或 deprecated path。

## 完成条件

被引入或退役的 capability 已显式声明、项目内闭合、可回滚，并在相称的状态层完成验证；任何未经验证的运行时效果都标记为未知。
