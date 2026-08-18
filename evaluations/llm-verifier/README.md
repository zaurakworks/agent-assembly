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

## 回执边界

`agent-assembly.verifier-evidence/v1` 只保存：

- request、criteria、候选轨迹 SHA-256；
- 固定 source commit、package version、backend/model 和参数；
- ranking、scores、comparison count、token usage 和 cache status；
- fixture 的限制声明。

它不保存候选正文、本地路径、凭据或 provider 原始错误，也不得解释为部署已通过
外部验收。

## 验证

```bash
python -m unittest discover -s tests -p "test_verifier_eval.py" -v
python -m unittest discover -s tests -v
python tools/cap.py skills-validate
git diff --check
```
