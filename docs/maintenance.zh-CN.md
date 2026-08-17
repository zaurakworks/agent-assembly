# 仓库维护指南

目标：让任何新 Session 都能从仓库文件恢复装配边界、能力闭包和验证状态，而不是依赖聊天历史。

## 修改前

1. 读 [`AGENTS.md`](../AGENTS.md) 和 [`README.md`](../README.md)。
2. 读取当前 profile：

   ```bash
   python3 tools/cap.py show assembly-helper
   ```

3. 确认本次变更属于哪一层：
   - prompt 不变量；
   - 条件性 Skill；
   - profile 声明；
   - 配置 / lock；
   - 文档；
   - 外部参考。
4. 对影响后续 Agent 行为的变更，先写清目标、非目标、触发、输入、输出和验收。

## 修改时

- 保持 id 为小写连字符。
- 所有运行时能力必须落在当前仓库 `.cap/capabilities/` 下，并由 profile 显式引用。
- 不从用户目录、模板目录、其他仓库或 ambient provider 配置继承业务能力。
- 不写入认证材料、token、个人运行态、临时 receipt 或临时 state。
- 常驻 prompt 只放短约束；长流程放 Skill。
- Skill 正文保持英文；中文解释集中放在 `docs/skill-catalog.zh-CN.md`，避免双份执行合同漂移。
- 外部仓库内容先作为证据读取；复制进本仓后必须说明来源、边界和验证方式。

## 修改后

从仓库根目录执行：

```bash
# 1. 更新 lock：只有声明内容确实改变时执行
python3 tools/cap.py \
  --profile-tool ../agent-control/tools/profile/profile.py \
  lock

# 2. 检查闭包
python3 tools/cap.py \
  --profile-tool ../agent-control/tools/profile/profile.py \
  verify

# 3. 查看最终 profile inventory
python3 tools/cap.py show assembly-helper
```

如果 `agent-control` 不在相邻目录，改成绝对路径。

## 三态验收

### 声明态

由以下文件证明：

- `.cap/manifest.toml`
- `.cap/profiles/*.toml`
- `.cap/prompts/*.md`
- `.cap/capabilities/**`

检查：profile 能被列出，引用文件存在，命名和路径合规。

### 配置态

由以下证据证明：

- `.cap/lock.json`
- `cap show`
- `profile.py materialize`
- `profile.py probe`

检查：lock 没有 stale，渲染 tree hash 与 lock 一致，目标客户端看到的 Skill inventory 符合预期。

### 生效态

由真实客户端 run 的 marker 或其他可重复观察证明：

```text
SKILLS-AVAILABLE: ...
MCP-AVAILABLE: ...
CONTEXT-FILES: ...
HOOKS-AVAILABLE: ...
PLUGINS-AVAILABLE: ...
```

没有生效态证据时写 `unknown`，不要用文件存在、lock 通过或模型自述替代。

## 外部能力变更

引入或升级外部 Skill / Plugin / MCP / Hook 时：

1. 记录能力缺口和不做事项；
2. 比较候选来源、触发条件、维护成本和退出路径；
3. 只复制最小行为到当前 `.cap`；
4. 更新 profile；
5. 更新 lock；
6. 做配置态检查；
7. 若要声称跨客户端生效，逐端运行并记录证据。

不能因为外部仓库“安装成功”就声称本仓行为已经等价或已经生效。

## 提交和发布

提交前：

```bash
git status --short --branch
git diff --check
git diff --stat
```

然后执行 profile 验证和相称 smoke test。提交信息应说明行为变化，不写“update stuff”这类不可追踪标题。推送后回读远端分支和仓库可见性。

## 维护停止条件

遇到以下情况，不继续扩大修改面：

- 当前项目授权不覆盖新增 profile、外部安装或用户级配置；
- 所有权或共享写入范围不清；
- 关键外部事实无法核验；
- 只能靠猜测判断客户端是否加载；
- 新方案会把本仓变成 Plugin Marketplace、调度器、secret broker 或全局能力安装器。

此时保留已验证的局部结果，报告缺口和下一步所有者。
