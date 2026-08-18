# LLM-as-a-Verifier 集成实验

本目录验证一个有边界的问题：固定版本的 `llm-verifier` 能否把多份 Agent
候选轨迹转换为可缓存、可回读、无正文泄漏的结构化 evidence。它不是新的
profile、Plugin、全局安装器或 AGX `verified` 判定。

## 能力缺口与非目标

- 缺口：当前装配评测只有人工 rubric，没有统一的候选排序 evidence。
- 目标：跑通请求、评分、缓存、输入变化失效、结构化回执和失败关闭。
- 非目标：不管理模型凭据，不评价真实模型质量，不改变任何 profile，不让分数
  覆盖确定性失败、人工决定或外部系统 readback。

固定来源是 PyPI `llm_verifier-0.2.0-py3-none-any.whl`，SHA-256 为
`5d1678c93d19874acd15999026117371c73367e3faac1712affe6dd7f38303af`。
官方 0.2.0 尚未包含上游
[PR #8](https://github.com/llm-as-a-verifier/llm-as-a-verifier/pull/8) 的缓存修复，
因此 runner 不直接复用用户给出的单一 cache 文件，而是用完整 request SHA-256
派生隔离缓存文件。不同输入不会共享 score cache；相同输入仍能稳定命中。

直接从固定 Git commit 安装曾在 Windows 实测失败：仓库内 benchmark data 的路径
超过默认 Windows checkout 长度。PyPI wheel 不包含这些运行时无关数据，可以正常
安装。上游若提供与 commit 对应的不可变 wheel/Release 资产，应优先替换当前依赖。
三个直接 provider SDK 也固定版本；完整传递依赖尚未形成 hash lock，因此本目录仍是
实验入口，不是 production dependency lock。

## 运行确定性集成 smoke

建议使用隔离虚拟环境：

```bash
python -m venv .venv-verifier
.venv-verifier/bin/pip install -r evaluations/llm-verifier/requirements.txt
.venv-verifier/bin/python tools/verifier_eval.py run \
  --request evaluations/llm-verifier/fixtures/bootstrap-evidence.json \
  --cache .tmp/verifier-cache.json
```

Windows 将虚拟环境命令替换为 `.venv-verifier\\Scripts\\python.exe` 和
`.venv-verifier\\Scripts\\pip.exe`。第一次输出 `cache_status=fresh`；相同命令
第二次输出 `cached`。修改任何 problem、候选、criterion 或 model 后，request digest
改变并选择新的隔离 cache，必须重新输出 `fresh`。

fixture backend 仍然调用 `llm_verifier.select`、PPT、评分提取和缓存实现，只把模型
调用替换为确定性响应。它证明集成路径，不证明模型质量；回执中的
`evidence_level` 因而只能是 `integration_smoke`。

## 真实 backend

把请求中的 `backend.kind` 改为 `environment`，并按照 `llm-verifier` 官方说明在进程
环境中提供 `OPENAI_BASE_URL`、`DEEPSEEK_API_KEY` 或 `VERTEX_API_KEY`。凭据不得写入
请求、cache、回执或仓库。真实调用固定使用 `on_error="raise"`，任何 verifier
错误都返回非零退出码和脱敏的 `VERIFIER_FAILED`，不会降级为 0.5 平局。

当前机器没有配置上述 backend，因此真实模型运行和模型质量均为 `unknown`。

## OMP backend（推荐的本地模型路由）

如果模型已经由 OMP 管理，把请求中的 `backend.kind` 改为 `omp`，并使用明确的
`provider/model` selector。评测合同不绑定 DeepSeek；示例只因本机 OMP 已配置该模型而
选择 `deepseek/deepseek-v4-flash`：

```bash
omp --version
.venv-verifier/bin/python tools/verifier_eval.py run \
  --request evaluations/llm-verifier/fixtures/omp-bootstrap-evidence.json \
  --cache .tmp/verifier-omp-cache.json
```

Windows 将 Python 路径替换为 `.venv-verifier\\Scripts\\python.exe`。runner 不读取、
复制或输出 OMP 凭据；OMP 自己通过现有 model registry 和 credential resolver 完成调用。

这里不能直接使用普通的 `omp -p` Agent 回合。实测 OMP 17.3.5 的普通回合会加载
coding-agent prompt，并可能按用户配置切换 fallback model：一次指定 DeepSeek 的失败请求
曾自动切换到另一个模型后返回成功；即使关闭扩展、tools、skills 和 rules，普通回合仍
报告约 87k 输入 token。这样的结果既昂贵，也无法证明指定模型实际完成了评分。

因此仓库显式加载 `omp-verifier.ts`，把 `/agent-assembly-verifier` 注册成命令，直接调用
OMP 的 stateless `completeSimple` 原语。每次调用同时满足：

- `--no-session --no-tools --no-extensions --no-skills --no-rules`；
- 只显式加载仓库内 verifier extension；
- 通过 `omp-no-fallback.yml` 在本次 invocation 禁用 retry 和 model fallback；
- 回读实际 `provider/model`、stop reason、usage 和评分文本；
- 串行执行 OMP completion，避免多个 CLI 进程争用同一认证/模型状态；
- 模型不一致、fallback 事件、超时、非正常停止、无效 A-T 评分或结构错误均失败关闭。

OMP 当前没有把 token logprob 分布暴露给这个入口，所以该 backend 使用 A-T **literal
score**，不是原版概率分布评分。回执明确写入
`scoring.mode=literal`、`logprob_distribution=false` 和对应 limitation；它可用于候选
排序和行为 smoke，不能伪装成更细粒度的概率证据。

模型可以在 tags 前生成分析，但 runner 只接受正常停止且各有唯一一组的
`<score_A>`/`<score_B>`，随后规范化为两个 tags；分析正文不会进入 evidence。截断、
缺 tag 或重复 tag 都不会被猜测或降级为平局。

2026-08-18 在 OMP 17.3.5 上使用示例 selector 的真实 smoke：fresh 运行完成 8 次模型
调用和 5 个比较，`pass > unknown > reject`，共 3,040 input tokens（其中 2,048
cache-read）、1,542 output tokens，provider 报告成本 `$0.0005763744`；相同请求第二次为 `cached`，模型调用和成本
均为 0。这个结果证明 OMP 路由、评分、缓存和 evidence 闭环，不证明任意真实任务上的
模型质量。

## 回执边界

`agent-assembly.verifier-evidence/v1` 只保存：

- request、criteria、候选轨迹 SHA-256；
- 固定 source commit、package version、backend/model 和参数；
- ranking、scores、comparison count、token usage 和 cache status；
- fixture 或 OMP literal scoring 的限制声明；
- OMP 新鲜调用实际使用的 serving model 和 provider 报告成本。

它不保存候选正文、本地路径、凭据或 provider 原始错误，也不得解释为部署已通过
外部验收。

## 验证

```bash
python -m unittest discover -s tests -p "test_verifier_eval.py" -v
python -m unittest discover -s tests -v
python tools/cap.py skills-validate
git diff --check
```
