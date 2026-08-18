#!/usr/bin/env python3
"""用于查看和使用显式 Agent 能力 profile 的 CLI。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_PROJECT = Path(__file__).resolve().parents[1]


def _default_profile_tool() -> Path:
    configured = os.environ.get("AGENT_CONTROL_PROFILE_TOOL")
    if configured:
        return Path(configured)
    candidates = (
        DEFAULT_PROJECT.parent / "agent-control" / "tools" / "caprun" / "caprun.py",
        DEFAULT_PROJECT.parent / "agent-control" / "tools" / "profile" / "profile.py",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return Path("caprun.py")


DEFAULT_PROFILE_TOOL = _default_profile_tool()
DEFAULT_CLEAN_HOME = DEFAULT_PROJECT.with_name(f"{DEFAULT_PROJECT.name}.clean-home")
DEFAULT_AGENT_HOME_ROOT = DEFAULT_PROJECT.with_name(f"{DEFAULT_PROJECT.name}.agent-homes")
DEFAULT_EMPLOYEE_ROOT = DEFAULT_PROJECT.with_name(f"{DEFAULT_PROJECT.name}.employees")
DEFAULT_PROFILE = "assembly-helper"
CLIENTS = ("codex", "qoder", "omp")
DEFAULT_CLI = "omp"
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CAPABILITY_KINDS = ("skills", "mcp", "hooks", "plugins")


def _decode_frontmatter_scalar(raw: str, path: Path, line: int) -> str:
    value = raw.strip()
    if not value:
        raise ValueError(f"{path}:{line}: 元数据值不能为空")
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line}: 无效双引号标量：{exc.msg}") from exc
        if not isinstance(decoded, str):
            raise ValueError(f"{path}:{line}: 元数据必须是字符串")
        return decoded
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise ValueError(f"{path}:{line}: 无效单引号标量")
        return value[1:-1].replace("''", "'")
    if value[0] in "|>[{&*!":
        raise ValueError(f"{path}:{line}: 本项目只允许简单字符串 frontmatter")
    return value


def _read_skill_metadata(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}:1: 缺少 YAML frontmatter 起始分隔符")
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError(f"{path}: 缺少 YAML frontmatter 结束分隔符") from exc

    metadata: dict[str, str] = {}
    for index, line in enumerate(lines[1:closing], 2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[0].isspace():
            raise ValueError(f"{path}:{index}: 本项目不允许嵌套 frontmatter")
        key, separator, raw = line.partition(":")
        if not separator or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise ValueError(f"{path}:{index}: 无效 frontmatter 字段")
        if key in metadata:
            raise ValueError(f"{path}:{index}: 重复 frontmatter 字段 {key}")
        metadata[key] = _decode_frontmatter_scalar(raw, path, index)
    return metadata


def _skill_metadata_report(project: Path) -> dict[str, object]:
    skill_root = project / ".cap" / "capabilities" / "skills"
    issues: list[str] = []
    skills: list[dict[str, str]] = []
    if not skill_root.is_dir():
        issues.append(f"{skill_root}: Skill 目录不存在")
    else:
        for skill_dir in sorted(path for path in skill_root.iterdir() if path.is_dir()):
            skill_file = skill_dir / "SKILL.md"
            relative = skill_file.relative_to(project).as_posix()
            if skill_dir.is_symlink() or skill_file.is_symlink():
                issues.append(f"{relative}: 不允许 symlink")
                continue
            if not skill_file.is_file():
                issues.append(f"{relative}: 文件不存在")
                continue
            try:
                metadata = _read_skill_metadata(skill_file)
            except (OSError, UnicodeError, ValueError) as exc:
                issues.append(str(exc))
                continue

            name = metadata.get("name", "")
            description = metadata.get("description", "")
            if not 1 <= len(name) <= 64 or not SKILL_NAME_PATTERN.fullmatch(name):
                issues.append(f"{relative}: name 必须是 1–64 字符的小写字母、数字和单连字符 id")
            elif name != skill_dir.name:
                issues.append(f"{relative}: name {name!r} 与目录 {skill_dir.name!r} 不一致")
            if not 1 <= len(description) <= 1024:
                issues.append(f"{relative}: description 必须是 1–1024 个字符")
            skills.append({"id": skill_dir.name, "path": relative, "name": name})

    return {
        "standard_conformance": "ok" if not issues else "invalid",
        "skills": skills,
        "issues": issues,
    }

AMBIENT_CONFIG_ENV = {
    "CODEX_HOME",
    "OMP_PROFILE",
    "PI_CODING_AGENT_DIR",
    "PI_CONFIG_DIR",
    "PI_CONFIG_FILES",
    "PI_PROFILE",
    "QODER_CONFIG_DIR",
    "QODER_WORKING_DIR",
}


class _CapArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        if "invalid choice: 'i'" in message or "invalid choice: 'interactive'" in message:
            message = f"{message}\n旧 interactive / i 已移除；请使用裸 cap"
        super().error(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _CapArgumentParser(
        prog="cap",
        description="裸 cap 启动显式 Agent profile；cap show 查看能力闭包和 CLI 装配。",
        epilog=(
            "高频使用：\n"
            "  cap\n"
            "\n"
            "独立查看：\n"
            "  cap show\n"
            "  cap show general\n"
            "  cap show general --cli omp\n"
            "\n"
            "显式自动化：\n"
            "  cap run assembly-helper -- -p \"帮我装配一个 review-agent\"\n"
            "  cap render assembly-helper --cli omp --output /tmp/rendered-cap\n"
            "  cap verify\n"
            "  cap skills-validate\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project",
        default=str(DEFAULT_PROJECT),
        metavar="目录",
        help="profile 项目根目录；默认是 agent-assembly 目录",
    )
    parser.add_argument(
        "--home",
        default=str(DEFAULT_CLEAN_HOME),
        metavar="目录",
        help="用于校验和渲染的 clean HOME；默认是 <project>.clean-home",
    )
    parser.add_argument(
        "--agent-home-root",
        default=str(DEFAULT_AGENT_HOME_ROOT),
        metavar="目录",
        help="持久 agent home 根目录；默认是 <project>.agent-homes",
    )
    parser.add_argument(
        "--employee-root",
        dest="agent_home_root",
        default=argparse.SUPPRESS,
        metavar="目录",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--profile-tool",
        default=str(DEFAULT_PROFILE_TOOL),
        metavar="文件",
        help="agent-control 的 caprun.py 或旧 profile.py 路径",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="命令",
        title="命令",
        description="裸 cap 用于高频启动；子命令用于查看、校验和自动化。",
    )

    skills_validate = subparsers.add_parser(
        "skills-validate",
        help="校验 Agent Skills 元数据",
        description="校验项目内 SKILL.md 的必需 frontmatter、名称和描述。",
    )

    agents = subparsers.add_parser(
        "agents",
        help="查看可用 agent",
        description="查看当前项目声明的全部 agent。",
    )
    agents.set_defaults(profile_tool_command="agents")

    profiles = subparsers.add_parser(
        "profiles",
        aliases=("list",),
        help="查看可用 profile（底层格式名）",
        description="查看当前项目声明的全部 profile。",
    )
    profiles.set_defaults(profile_tool_command="list")

    clients = subparsers.add_parser(
        "clients",
        help="查看客户端 CLI 解析路径",
        description="查看 codex、qoder、omp 在当前 PATH 中解析到哪个可执行文件及其版本输出。",
    )
    clients.set_defaults(profile_tool_command="clients")


    show = subparsers.add_parser(
        "show",
        aliases=("explain",),
        help="查看 profile 的公共闭包或 CLI 装配",
        description="先查看 prompt、skills、MCP、hooks、plugins 与各 CLI hash；可选展开一个 CLI 的真实目标文件树。",
    )
    show.add_argument("profile", nargs="?", default=None, help="profile 名；省略时在 TTY 中选择")
    show.add_argument("--cli", choices=CLIENTS, help="展开指定客户端的真实装配")
    show.set_defaults(profile_tool_command="explain")

    use = subparsers.add_parser(
        "use",
        aliases=("launch",),
        help="显式使用 profile 启动一个 CLI",
        description="显式指定 profile 和目标 CLI，在当前工作目录中用持久 agent home 启动客户端。",
    )
    use.add_argument("profile", nargs="?", default=DEFAULT_PROFILE, help="profile 名；默认 assembly-helper")
    use.add_argument("--cli", default=DEFAULT_CLI, choices=CLIENTS, help="要启动的客户端 CLI；默认 omp")
    use.add_argument(
        "--receipt",
        default=None,
        metavar="文件",
        help="启动收据路径；默认 <project>.runs/<profile>-<cli>-<时间戳>.receipt.json",
    )
    use.add_argument(
        "--workdir",
        default=None,
        metavar="目录",
        help="客户端工作目录；默认当前目录",
    )
    use.add_argument(
        "--fresh",
        action="store_true",
        help="使用一次性临时 runtime；默认 OMP 使用持久 agent home",
    )
    use.set_defaults(profile_tool_command="launch")

    run = subparsers.add_parser(
        "run",
        help="使用 profile 执行一次批处理命令",
        description="选择 profile 和目标 CLI，在当前工作目录中执行一次 batch 命令并记录 state；必须在 -- 后提供客户端命令参数。",
    )
    run.add_argument("profile", nargs="?", default=DEFAULT_PROFILE, help="profile 名；默认 assembly-helper")
    run.add_argument("--cli", default=DEFAULT_CLI, choices=CLIENTS, help="要运行的客户端 CLI；默认 omp")
    run.add_argument(
        "--state",
        default=None,
        metavar="目录",
        help="观察 state 目录；默认 <project>.runs/<profile>-<cli>-<时间戳>.state",
    )
    run.add_argument(
        "--workdir",
        default=None,
        metavar="目录",
        help="客户端工作目录；默认当前目录",
    )
    run.add_argument(
        "--fresh",
        action="store_true",
        help="使用一次性临时 runtime；默认 OMP 使用持久 agent home",
    )
    run.set_defaults(profile_tool_command="run")

    render = subparsers.add_parser(
        "render",
        aliases=("materialize",),
        help="渲染 profile，不启动 CLI",
        description="把 profile 渲染到指定空目录，用于检查目标 CLI 会看到的配置。",
    )
    render.add_argument("profile", nargs="?", default=DEFAULT_PROFILE, help="profile 名；默认 assembly-helper")
    render.add_argument("--cli", default=DEFAULT_CLI, choices=CLIENTS, help="要渲染的客户端 CLI；默认 omp")
    render.add_argument("--output", required=True, metavar="目录", help="已存在且为空的输出目录")
    render.set_defaults(profile_tool_command="materialize")

    lock = subparsers.add_parser(
        "lock",
        help="刷新 .cap/lock.json",
        description="重新计算 profile 声明、能力文件和三端渲染 hash，并写入 lock。",
    )
    lock.set_defaults(profile_tool_command="lock")

    verify = subparsers.add_parser(
        "verify",
        help="校验 lock 和能力闭包",
        description="校验当前声明、能力闭包和 lock 是否一致。",
    )
    verify.set_defaults(profile_tool_command="verify")

    return parser


def _base_args(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        str(Path(args.profile_tool).expanduser()),
        "--project",
        str(Path(args.project).expanduser()),
    ]

def _uses_caprun(args: argparse.Namespace) -> bool:
    return Path(args.profile_tool).name == "caprun.py"


def _run_path(args: argparse.Namespace, suffix: str) -> str:
    root = Path(args.project).expanduser()
    run_dir = root.with_name(f"{root.name}.runs")
    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return str(run_dir / f"{args.profile}-{args.cli}-{stamp}-{os.getpid()}-{time.time_ns()}.{suffix}")


def _workdir(args: argparse.Namespace) -> Path:
    return (Path(args.workdir).expanduser() if args.workdir else Path.cwd()).resolve(strict=True)


def _agent_home_dir(args: argparse.Namespace) -> Path:
    return Path(args.agent_home_root).expanduser() / args.profile / args.cli


def _passthrough(values: list[str]) -> list[str]:
    return values


def _profile_args(args: argparse.Namespace) -> list[str]:
    base = _base_args(args)
    command = args.profile_tool_command
    if command in {"list", "lock", "verify"}:
        return [*base, command]
    if command == "explain":
        return [*base, "explain", "--profile", args.profile]
    if command == "materialize":
        return [
            *base,
            "render" if _uses_caprun(args) else "materialize",
            "--client",
            args.cli,
            "--profile",
            args.profile,
            "--output",
            args.output,
        ]
    if command == "launch":
        receipt = Path(args.receipt).expanduser() if args.receipt else Path(
            _run_path(args, "receipt.json")
        )
        receipt.parent.mkdir(parents=True, exist_ok=True)
        if _uses_caprun(args):
            return [
                *base,
                "run",
                "--client",
                args.cli,
                "--profile",
                args.profile,
                "--receipt",
                str(receipt),
                "--",
                *_passthrough(args.client_args),
            ]
        return [
            *base,
            "launch",
            "--client",
            args.cli,
            "--profile",
            args.profile,
            "--receipt",
            str(receipt),
            "--workdir",
            str(_workdir(args)),
            "--",
            *_passthrough(args.client_args),
        ]
    if command == "run":
        state = args.state or _run_path(args, "state")
        Path(state).mkdir(parents=True, exist_ok=True)
        if _uses_caprun(args):
            return [
                *base,
                "run",
                "--client",
                args.cli,
                "--profile",
                args.profile,
                "--receipt",
                str(Path(state) / "receipt.json"),
                "--",
                *_passthrough(args.client_args),
            ]
        return [
            *base,
            "run",
            "--client",
            args.cli,
            "--profile",
            args.profile,
            "--state",
            state,
            "--workdir",
            str(_workdir(args)),
            "--",
            *_passthrough(args.client_args),
        ]
    raise AssertionError(f"unsupported command: {command}")


def _migrate_default_agent_home_root(args: argparse.Namespace) -> None:
    target = Path(args.agent_home_root).expanduser()
    if target != DEFAULT_AGENT_HOME_ROOT:
        return
    legacy = DEFAULT_EMPLOYEE_ROOT
    if legacy.exists() and not target.exists():
        shutil.move(str(legacy), str(target))


def _client_inventory() -> dict[str, object]:
    clients: dict[str, object] = {}
    for name in CLIENTS:
        resolved = shutil.which(name)
        version: dict[str, object] = {"exit_code": None, "output": None}
        if resolved:
            try:
                completed = subprocess.run(
                    [resolved, "--version"],
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=5,
                )
                version = {
                    "exit_code": completed.returncode,
                    "output": (completed.stdout + completed.stderr).strip(),
                }
            except (OSError, subprocess.TimeoutExpired) as error:
                version = {"exit_code": None, "output": str(error)}
        clients[name] = {"path": resolved, "version": version}
    return {"clients": clients}


def _available_profiles(args: argparse.Namespace, env: dict[str, str]) -> list[str]:
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(args.profile_tool).expanduser()),
            "--project",
            str(Path(args.project).expanduser()),
            "list",
        ],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    if completed.returncode != 0:
        print(completed.stderr.strip() or completed.stdout.strip(), file=sys.stderr)
        return []
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        print(f"无法解析 profile 列表：{error}", file=sys.stderr)
        return []
    profiles = data.get("profiles", [])
    return [item for item in profiles if isinstance(item, str)]


def _choose(label: str, choices: list[str], default: str) -> str:
    print(f"\n选择 {label}：")
    for index, choice in enumerate(choices, start=1):
        marker = " [默认]" if choice == default else ""
        print(f"  {index}. {choice}{marker}")
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit():
            offset = int(raw) - 1
            if 0 <= offset < len(choices):
                return choices[offset]
        if raw in choices:
            return raw
        print(f"无效选择：{raw}")


def _require_tty(label: str, explicit_example: str) -> bool:
    if sys.stdin.isatty() and sys.stdout.isatty():
        return True
    print(
        f"{label} 需要交互式 stdin/stdout；非交互调用请使用：{explicit_example}",
        file=sys.stderr,
    )
    return False


def _interactive_use(args: argparse.Namespace, env: dict[str, str]) -> int:
    profiles = _available_profiles(args, env)
    if not profiles:
        print("没有可用 profile。", file=sys.stderr)
        return 2
    profile_default = DEFAULT_PROFILE if DEFAULT_PROFILE in profiles else profiles[0]
    args.profile = _choose("profile", profiles, profile_default)
    args.cli = _choose("CLI", list(CLIENTS), DEFAULT_CLI)
    extra = input("客户端参数（可空；例如 --version）: ").strip()
    args.client_args = shlex.split(extra) if extra else []
    args.receipt = None
    args.workdir = None
    args.fresh = False
    args.profile_tool_command = "launch"
    return _run_selected(args, env)


def _profile_json(args: argparse.Namespace, env: dict[str, str], stage: str) -> dict[str, object] | None:
    try:
        completed = subprocess.run(
            _profile_args(args),
            capture_output=True,
            check=False,
            env=env,
            text=True,
        )
    except OSError as error:
        print(f"{stage} 失败：{error}", file=sys.stderr)
        return None
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"退出码 {completed.returncode}"
        print(f"{stage} 失败：{detail}", file=sys.stderr)
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        print(f"{stage} 输出解析失败：{error}", file=sys.stderr)
        return None
    if not isinstance(payload, dict):
        print(f"{stage} 输出解析失败：顶层必须是 JSON object", file=sys.stderr)
        return None
    return payload


def _render_preview(args: argparse.Namespace, env: dict[str, str]) -> dict[str, object] | None:
    try:
        with tempfile.TemporaryDirectory(prefix=f"cap-show-{args.profile}-{args.cli}-") as temporary:
            preview_args = argparse.Namespace(**vars(args))
            preview_args.profile_tool_command = "materialize"
            preview_args.output = temporary
            rendered = _profile_json(preview_args, env, "render")
            if rendered is None:
                return None
            tree_hash = rendered.get("tree_hash")
            if not isinstance(tree_hash, str):
                print("render 输出解析失败：缺少字符串 tree_hash", file=sys.stderr)
                return None
            root = Path(temporary)
            files = sorted(
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            )
            return {
                "client": args.cli,
                "files": files,
                "tree_hash": tree_hash,
            }
    except OSError as error:
        print(f"目标文件枚举失败：{error}", file=sys.stderr)
        return None


def _show(args: argparse.Namespace, env: dict[str, str]) -> int:
    interactive = args.profile is None
    if interactive:
        profiles = _available_profiles(args, env)
        if not profiles:
            print("没有可用 profile。", file=sys.stderr)
            return 2
        profile_default = DEFAULT_PROFILE if DEFAULT_PROFILE in profiles else profiles[0]
        args.profile = _choose("profile", profiles, profile_default)

    explanation = _profile_json(args, env, "explain")
    if explanation is None:
        return 2

    if interactive:
        print(json.dumps(explanation, ensure_ascii=False, indent=2))
        selected = _choose("CLI 装配", ["不展开", *CLIENTS], "不展开")
        if selected == "不展开":
            return 0
        args.cli = selected
        preview = _render_preview(args, env)
        if preview is None:
            return 2
        print(json.dumps({"preview": preview}, ensure_ascii=False, indent=2))
        return 0

    if args.cli:
        preview = _render_preview(args, env)
        if preview is None:
            return 2
        explanation["preview"] = preview
    print(json.dumps(explanation, ensure_ascii=False, indent=2))
    return 0


def _render_for_agent_home(args: argparse.Namespace, env: dict[str, str], agent_home: Path) -> str:
    agent_home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"cap-render-{args.profile}-{args.cli}-") as temporary:
        completed = subprocess.run(
            [
                *_base_args(args),
                "render" if _uses_caprun(args) else "materialize",
                "--client",
                args.cli,
                "--profile",
                args.profile,
                "--output",
                temporary,
            ],
            capture_output=True,
            check=False,
            env=env,
            text=True,
        )
        if completed.returncode != 0:
            print(completed.stderr.strip() or completed.stdout.strip(), file=sys.stderr)
            raise SystemExit(completed.returncode)
        try:
            tree_hash = json.loads(completed.stdout).get("tree_hash", "unknown")
        except json.JSONDecodeError:
            tree_hash = "unknown"
        rendered = Path(temporary)
        rendered_snapshot = agent_home / ".cap-rendered"
        if rendered_snapshot.exists():
            shutil.rmtree(rendered_snapshot)
        rendered_snapshot.mkdir(parents=True, exist_ok=True)
        for file_name in ("config.yml", "mcp.json", "system-prompt.md"):
            source = rendered / file_name
            if source.is_file():
                shutil.copy2(source, rendered_snapshot / file_name)
                if file_name == "config.yml" and (agent_home / file_name).exists():
                    continue
                shutil.copy2(source, agent_home / file_name)
        skills_source = rendered / "skills"
        skills_snapshot = rendered_snapshot / "skills"
        if skills_snapshot.exists():
            shutil.rmtree(skills_snapshot)
        if skills_source.is_dir():
            shutil.copytree(skills_source, skills_snapshot)
        skills_target = agent_home / "skills"
        if skills_target.exists():
            shutil.rmtree(skills_target)
        if skills_source.is_dir():
            shutil.copytree(skills_source, skills_target)
        return str(tree_hash)


def _omp_command(agent_home: Path, forwarded: list[str]) -> list[str]:
    executable = shutil.which("omp") or "omp"
    prompt = (agent_home / "system-prompt.md").read_text(encoding="utf-8").strip() + "\n"
    skills_root = agent_home / "skills"
    skill_names = sorted(item.name for item in skills_root.iterdir() if item.is_dir()) if skills_root.is_dir() else []
    skill_args = ["--skills", ",".join(skill_names)] if skill_names else ["--no-skills"]
    return [
        executable,
        "--config",
        str(agent_home / "config.yml"),
        "--append-system-prompt",
        prompt,
        *skill_args,
        "--no-extensions",
        "--no-rules",
        *forwarded,
    ]


def _agent_home_env(base_env: dict[str, str], agent_home: Path) -> dict[str, str]:
    env = base_env.copy()
    for name in AMBIENT_CONFIG_ENV:
        env.pop(name, None)
    home = agent_home / "home"
    home.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "HOME": str(home),
            "OMP_PROFILE": "default",
            "PI_CODING_AGENT_DIR": str(agent_home),
            "PI_CONFIG_DIR": str(agent_home),
            "PI_CONFIG_FILES": str(agent_home / "config.yml"),
            "PI_PROFILE": "default",
        }
    )
    return env


def _write_receipt(args: argparse.Namespace, receipt: Path, return_code: int, tree_hash: str, agent_home: Path) -> None:
    payload = {
        "version": 1,
        "client": args.cli,
        "profile": args.profile,
        "exit_code": return_code,
        "persistent_agent_home": True,
        "agent_home": str(agent_home),
        "workdir": str(_workdir(args)),
        "output_tree_hash": tree_hash,
        "forwarded_argument_count": len(args.client_args),
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_omp_agent_home(args: argparse.Namespace, env: dict[str, str]) -> int:
    agent_home = _agent_home_dir(args)
    tree_hash = _render_for_agent_home(args, env, agent_home)
    receipt = Path(args.receipt).expanduser() if getattr(args, "receipt", None) else Path(_run_path(args, "receipt.json"))
    completed = subprocess.run(
        _omp_command(agent_home, _passthrough(args.client_args)),
        cwd=str(_workdir(args)),
        env=_agent_home_env(env, agent_home),
        check=False,
    )
    _write_receipt(args, receipt, completed.returncode, tree_hash, agent_home)
    return completed.returncode if completed.returncode >= 0 else 128 + abs(completed.returncode)


def _run_selected(args: argparse.Namespace, env: dict[str, str]) -> int:
    if args.profile_tool_command in {"launch", "run"} and args.cli == "omp" and not args.fresh:
        return _run_omp_agent_home(args, env)
    completed = subprocess.run(_profile_args(args), env=env, check=False)
    return completed.returncode

def _ensure_capability_store_dirs(project: Path) -> None:
    capabilities = project / ".cap" / "capabilities"
    if not capabilities.is_dir():
        return
    for kind in CAPABILITY_KINDS:
        (capabilities / kind).mkdir(exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    passthrough: list[str] = []
    if "--" in raw_args:
        separator = raw_args.index("--")
        passthrough = raw_args[separator + 1 :]
        raw_args = raw_args[:separator]
    parser = _build_parser()
    args = parser.parse_args(raw_args)
    if hasattr(args, "profile_tool_command") and args.profile_tool_command in {"launch", "run"}:
        args.client_args = passthrough
    if args.command is None and not _require_tty(
        "裸 cap",
        "cap use <profile> --cli <client> [-- <客户端参数>]",
    ):
        return 2
    if (
        getattr(args, "profile_tool_command", None) == "explain"
        and args.profile is None
        and not _require_tty("cap show", "cap show <profile> [--cli <client>]")
    ):
        return 2
    if args.command == "skills-validate":
        report = _skill_metadata_report(Path(args.project).expanduser().resolve())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["standard_conformance"] == "ok" else 2
    _ensure_capability_store_dirs(Path(args.project).expanduser().resolve())
    if getattr(args, "profile_tool_command", None) == "verify":
        report = _skill_metadata_report(Path(args.project).expanduser().resolve())
        if report["standard_conformance"] != "ok":
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2
    _migrate_default_agent_home_root(args)
    clean_home = Path(args.home).expanduser()
    clean_home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = str(clean_home)
    if getattr(args, "profile_tool_command", None) == "clients":
        print(json.dumps(_client_inventory(), ensure_ascii=False, indent=2))
        return 0
    if getattr(args, "profile_tool_command", None) == "agents":
        print(json.dumps({"agents": _available_profiles(args, env)}, ensure_ascii=False, indent=2))
        return 0
    if args.command is None:
        return _interactive_use(args, env)
    if getattr(args, "profile_tool_command", None) == "explain":
        return _show(args, env)
    if getattr(args, "profile_tool_command", None) == "run" and not args.client_args:
        print(
            "cap run 需要在 -- 后提供客户端 batch 参数；否则目标 CLI 可能进入交互/恢复等待，看起来像卡住。\n"
            "示例：cap run assembly-helper -- -p \"帮我装配一个 review-agent\"\n"
            "如果要交互式启动，请使用裸 cap",
            file=sys.stderr,
        )
        return 2
    return _run_selected(args, env)


if __name__ == "__main__":
    raise SystemExit(main())
