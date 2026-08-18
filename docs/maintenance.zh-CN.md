# 仓库维护指南

目标：让任何新 Session 都能从仓库文件恢复装配边界、能力闭包和验证状态，而不是依赖聊天历史。

## 修改前

1. 读 [`AGENTS.md`](../AGENTS.md) 和 [`README.md`](../README.md)。
2. 读取当前 profile。TTY 中可以先选择；脚本必须显式指定 profile：

   ```bash
   python3 tools/cap.py show
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
- 项目新增或替换的运行时能力必须落在当前仓库 `.cap/capabilities/` 下，并由 profile 的 `add`／`replace` 显式引用。
- 用户环境只允许通过已审批 `real-home` manifest、workspace pin 和 derived binding 进入；不得从未绑定的用户目录、模板目录、其他仓库或 ambient provider 配置补齐业务能力。
- 不把认证材料、token、个人运行态、临时 receipt、base manifest、pin 或 binding 写入本仓。
- 常驻 prompt 只放短约束；长流程放 Skill。
- 快速迭代阶段，Skill 的 `description` 和正文使用中文；`name`、目录 id、路径、命令和配置键保持规范形式。
- `.cap/capabilities/skills/<name>/SKILL.md` 是唯一全文合同；不在 `docs/skills/` 维护需要逐项同步的另一语言镜像。
- 外部仓库内容先作为证据读取；复制进本仓后必须说明来源、边界和验证方式。

## OpenSpec 工作流

OpenSpec 固定为仓库内开发依赖。先执行 `npm install`，再通过 `npx openspec` 调用；不得依赖用户级全局安装。

```bash
npx openspec status --change <change-id> --json
npx openspec instructions <artifact> --change <change-id> --json
npx openspec validate <change-id> --strict --json
```

供人阅读的 proposal、spec、design、tasks 正文使用中文，保留 OpenSpec 解析要求的英文结构关键字。初始化保持 `--tools none`：OpenSpec CLI 管理 `openspec/` 规划资产；六个中文 Workflow Skill 合同由 `.cap` 显式声明，不向 `.agents`、`.omp`、`.qoder` 生成 profile 外运行时能力。

## 修改后

从仓库根目录执行：

```bash
# 1. 检查 Skill 标准元数据
python3 tools/cap.py skills-validate

# 2. 更新项目层 lock：只有声明内容确实改变时执行
python3 tools/cap.py lock

# 3. 项目层变化后重建两个 derived binding；不得自动刷新 base pin
PROFILE_TOOL=../agent-control/tools/profile/profile.py
for profile in general assembly-helper; do
  python3 "$PROFILE_TOOL" --project . bind \
    --profile "$profile" \
    --base-manifest "$HOME/.cap-user-state/locks/real-home.manifest.json" \
    --base-pin "$HOME/work/_org/locks/agent-assembly-general/real-home.pin.json" \
    --binding-dir "$HOME/work/_org/locks/agent-assembly-general/bindings"
done

# 4. 检查元数据、项目 lock、base pin 和全部 binding
python3 tools/cap.py verify

# 5. 查看最终公共 inventory，并展开一个 CLI 的真实目标文件树
python3 tools/cap.py show assembly-helper
python3 tools/cap.py show general
python3 tools/cap.py show general --cli omp

# 6. 验证活动 OpenSpec change
npx openspec validate <change-id> --strict --json
```

裸 `cap` 专用于高频启动；`cap show` 专用于查看。CLI 展开使用临时 render，只输出相对文件树和 tree hash，不启动客户端或保留临时目录。`run` 与带 `--output` 的 `render` 是参数完整、可在非 TTY 中执行的自动化接口。旧 `interactive` / `i` 不保留兼容层。当前只注册 Codex、Qoder、OMP；Claude adapter 延期到具备真实 CLI、render 和运行证据后实施，当前不得宣称支持。

如果 `agent-control` 不在相邻目录，改成绝对路径。

## 证据分层

### Skill 标准合规

由 `SKILL.md` frontmatter、目录 id 和 `python3 tools/cap.py skills-validate` 证明。标准合规不是运行时状态，也不能替代 profile 闭包或客户端观察。

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
- `$HOME/.cap-user-state/locks/real-home.manifest.json`
- `$HOME/work/_org/locks/agent-assembly-general/real-home.pin.json`
- `$HOME/work/_org/locks/agent-assembly-general/bindings/*.binding.json`
- `cap show`
- `profile.py materialize`
- 真实客户端 runtime environment

检查：项目 lock 没有 stale，base active digest 被 workspace pin 明确批准，derived binding 同时匹配 base digest 与 layer digest，渲染 tree hash 与 lock 一致，客户端保留真实 `HOME` 且配置/Session 状态根保持 profile 隔离。

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
