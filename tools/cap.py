#!/usr/bin/env python3
"""用于查看和使用显式 Agent 能力 profile 的 CLI。"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
import re
import shlex
import sqlite3
import shutil
import subprocess
import stat
import sys
import tempfile
import time
from pathlib import Path
import yaml

DEFAULT_PROJECT = Path(__file__).resolve().parents[1]


def _default_profile_tool() -> Path:
    configured = os.environ.get("AGENT_CONTROL_PROFILE_TOOL")
    if configured:
        return Path(configured)
    candidate = (
        DEFAULT_PROJECT.parent
        / "agent-control"
        / "tools"
        / "profile"
        / "profile.py"
    )
    return candidate if candidate.is_file() else Path("profile.py")


DEFAULT_PROFILE_TOOL = _default_profile_tool()
DEFAULT_REAL_HOME = Path.home()
DEFAULT_AGENT_HOME_ROOT = DEFAULT_PROJECT.with_name(f"{DEFAULT_PROJECT.name}.agent-homes")
DEFAULT_BASE_MANIFEST = DEFAULT_REAL_HOME / ".cap-user-state" / "locks" / "real-home.manifest.json"
DEFAULT_WORKSPACE_CONTROL = DEFAULT_REAL_HOME / "work" / "_org" / "locks" / DEFAULT_PROJECT.name
DEFAULT_BASE_PIN = DEFAULT_WORKSPACE_CONTROL / "real-home.pin.json"
DEFAULT_BINDING_DIR = DEFAULT_WORKSPACE_CONTROL / "bindings"
DEFAULT_AUTH_ROOT = DEFAULT_PROJECT.with_name(f"{DEFAULT_PROJECT.name}.auth")
DEFAULT_PROFILE = "assembly-helper"
RUNNABLE_PROFILES = ("assembly-helper", "general")
CLIENTS = ("codex", "qoder", "omp")
DEFAULT_CLI = "omp"
DEFAULT_OMP_RUNTIME_ID = "default"
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

OMP_AMBIENT_AUTH_ENV = {
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "ANTHROPIC_SEARCH_BASE_URL",
    "AWS_CONFIG_FILE",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_EC2_METADATA_DISABLED",
    "AWS_EC2_METADATA_SERVICE_ENDPOINT",
    "AWS_EC2_METADATA_SERVICE_ENDPOINT_MODE",
    "AWS_PROFILE",
    "AWS_ROLE_ARN",
    "AWS_ROLE_SESSION_NAME",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_BASE_URL",
    "AZURE_OPENAI_DEPLOYMENT_NAME_MAP",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_RESOURCE_NAME",
    "CLAUDE_CODE_CLIENT_CERT",
    "CLAUDE_CODE_CLIENT_KEY",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLOUDSDK_CONFIG",
    "COPILOT_GITHUB_TOKEN",
    "FOUNDRY_BASE_URL",
    "FUGU_BASE_URL",
    "GCLOUD_PROJECT",
    "GCP_PROJECT",
    "GITLAB_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_PROJECT_ID",
    "GOOGLE_VERTEX_LOCATION",
    "HF_TOKEN",
    "KIMI_CODE_BASE_URL",
    "KIMI_CODE_OAUTH_HOST",
    "KIMI_OAUTH_HOST",
    "LITELLM_BASE_URL",
    "LLAMA_CPP_BASE_URL",
    "LM_STUDIO_BASE_URL",
    "MOONSHOT_BASE_URL",
    "NODE_EXTRA_CA_CERTS",
    "OLLAMA_BASE_URL",
    "OLLAMA_HOST",
    "OMP_AUTH_BROKER_TOKEN",
    "OMP_AUTH_BROKER_URL",
    "OPENAI_BASE_URL",
    "PERPLEXITY_COOKIES",
    "SAKANA_BASE_URL",
    "UMANS_WEBSEARCH_PROVIDER",
    "VERTEX_LOCATION",
}
OMP_AMBIENT_CREDENTIAL_SUFFIXES = (
    "_API_KEY",
    "_ACCESS_TOKEN",
    "_OAUTH_TOKEN",
    "_BEARER_TOKEN",
    "_HUB_TOKEN",
    "_SECRET_ACCESS_KEY",
    "_SESSION_TOKEN",
)

OMP_AMBIENT_MCP_DENYLIST = ("codegraph",)


def _is_ambient_credential_name(name: str) -> bool:
    return name.endswith(OMP_AMBIENT_CREDENTIAL_SUFFIXES)


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
        default=str(DEFAULT_REAL_HOME),
        metavar="目录",
        help="真实用户 HOME；默认使用当前用户 HOME",
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
        help="agent-control 的 profile.py 路径",
    )
    parser.add_argument(
        "--base-manifest",
        default=str(DEFAULT_BASE_MANIFEST),
        metavar="文件",
        help="私有 real-home manifest 路径",
    )
    parser.add_argument(
        "--base-pin",
        default=str(DEFAULT_BASE_PIN),
        metavar="文件",
        help="workspace real-home 审批 pin 路径",
    )
    parser.add_argument(
        "--binding-dir",
        default=str(DEFAULT_BINDING_DIR),
        metavar="目录",
        help="derived profile binding 目录",
    )
    parser.add_argument(
        "--auth-root",
        default=str(DEFAULT_AUTH_ROOT),
        metavar="目录",
        help="一次性 runtime 使用的私有认证库",
    )
    parser.add_argument(
        "--omp-runtime-id",
        default=DEFAULT_OMP_RUNTIME_ID,
        metavar="ID",
        help="用户级 OMP runtime id；默认 default",
    )
    parser.add_argument(
        "--omp-runtime-root",
        default=None,
        metavar="目录",
        help="显式用户级 OMP runtime 根；默认 $HOME/.cap-user-state/runtimes/omp/<id>",
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

    migrate = subparsers.add_parser(
        "migrate-omp-runtime",
        help="检查或迁移持久 OMP 共享 runtime",
        description="默认输出无 secret dry-run plan；--apply 安装共享 runtime，--cleanup 在行为验证后删除旧 CAP 状态。",
    )
    migrate_mode = migrate.add_mutually_exclusive_group()
    migrate_mode.add_argument(
        "--apply",
        action="store_true",
        help="备份旧状态并安装共享 runtime",
    )
    migrate_mode.add_argument(
        "--cleanup",
        action="store_true",
        help="删除已迁移且完成行为验证的旧 CAP 状态",
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

def _binding_args(args: argparse.Namespace) -> list[str]:
    return [
        "--base-manifest",
        str(Path(args.base_manifest).expanduser()),
        "--base-pin",
        str(Path(args.base_pin).expanduser()),
        "--binding-dir",
        str(Path(args.binding_dir).expanduser()),
    ]


def _run_path(args: argparse.Namespace, suffix: str) -> str:
    root = Path(args.project).expanduser()
    run_dir = root.with_name(f"{root.name}.runs")
    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return str(run_dir / f"{args.profile}-{args.cli}-{stamp}-{os.getpid()}-{time.time_ns()}.{suffix}")


def _workdir(args: argparse.Namespace) -> Path:
    return (Path(args.workdir).expanduser() if args.workdir else Path.cwd()).resolve(strict=True)


def _agent_home_root(args: argparse.Namespace) -> Path:
    return Path(args.agent_home_root).expanduser().absolute()


def _runtime_real_home(args: argparse.Namespace) -> Path:
    return Path(
        getattr(args, "_real_home", getattr(args, "home", DEFAULT_REAL_HOME))
    ).expanduser().absolute()


def _omp_runtime_id(args: argparse.Namespace) -> str:
    value = str(getattr(args, "omp_runtime_id", DEFAULT_OMP_RUNTIME_ID))
    if not SKILL_NAME_PATTERN.fullmatch(value):
        raise _MigrationError(
            "OMP runtime id must be a lowercase kebab-case identifier"
        )
    return value


def _agent_home_dir(args: argparse.Namespace) -> Path:
    parent = (
        _runtime_real_home(args)
        / ".cap-user-state"
        / "runtimes"
        / "omp"
    )
    expected = parent / _omp_runtime_id(args)
    explicit_root = getattr(args, "omp_runtime_root", None)
    if explicit_root:
        candidate = Path(explicit_root).expanduser().absolute()
        if candidate != expected:
            raise _MigrationError(
                "explicit OMP runtime root must equal the approved HOME/id path"
            )
    return expected


def _project_shared_omp_home(args: argparse.Namespace) -> Path:
    return _agent_home_root(args) / "shared" / "omp"


def _legacy_omp_homes(args: argparse.Namespace) -> dict[str, Path]:
    root = _agent_home_root(args)
    return {
        profile: root / profile / "omp"
        for profile in RUNNABLE_PROFILES
    }


def _global_render_root(args: argparse.Namespace) -> Path:
    return (
        _runtime_real_home(args)
        / ".cap-user-state"
        / "renders"
        / "omp"
    )


def _profile_render_parent(args: argparse.Namespace) -> Path:
    return _global_render_root(args)


def _project_render_root(args: argparse.Namespace) -> Path:
    return _agent_home_root(args) / "renders"


def _migration_backup_root(args: argparse.Namespace) -> Path:
    return (
        _agent_home_root(args)
        / "migration-backup"
        / "global-omp-runtime"
    )


def _shared_runtime_marker(args: argparse.Namespace) -> Path:
    return _agent_home_dir(args) / ".cap-shared-runtime.json"


class _MigrationError(ValueError):
    """Report a fail-closed shared-runtime migration error."""


@dataclass(frozen=True)
class _RuntimeSummary:
    label: str
    root: Path
    exists: bool
    auth_count: int
    auth_digest: str
    settings_digest: str
    schema_digest: str
    config: dict[str, object]
    sessions: Mapping[str, str]


def _digest_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _digest_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _digest_bytes(payload)


def _assert_managed_path(
    root: Path, candidate: Path, label: str, *, allow_missing: bool = False
) -> Path:
    root = root.expanduser().absolute()
    candidate = candidate.expanduser().absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise _MigrationError(f"{label} is outside the CAP state root") from error
    if not relative.parts:
        raise _MigrationError(f"{label} must not be the CAP state root")
    current = root
    for part in relative.parts:
        current = current / part
        if not current.exists() and not current.is_symlink():
            if allow_missing:
                continue
            raise _MigrationError(f"{label} does not exist")
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise _MigrationError(f"{label} contains a symlink")
    return candidate


def _validate_private_runtime(root: Path, label: str) -> None:
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise _MigrationError(
            f"{label} must be a current-user directory"
        )
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise _MigrationError(
            f"{label} must not grant group or other access"
        )


def _reject_unsafe_tree(root: Path, label: str) -> None:
    for path in [root, *root.rglob("*")]:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise _MigrationError(f"{label} contains a symlink")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise _MigrationError(f"{label} contains a hard-linked file")
        if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
            raise _MigrationError(f"{label} contains a special file")


def _strip_legacy_broker(config: dict[str, object]) -> dict[str, object]:
    copied = json.loads(json.dumps(config))
    auth = copied.get("auth")
    if isinstance(auth, dict):
        auth.pop("broker", None)
        if not auth:
            copied.pop("auth", None)
    copied.setdefault("memory", {})
    memory = copied["memory"]
    if not isinstance(memory, dict):
        raise _MigrationError("OMP setting memory must be an object")
    memory["backend"] = "off"
    return copied


def _read_runtime_config(root: Path, label: str) -> dict[str, object]:
    path = root / "config.yml"
    if not path.is_file():
        return {"memory": {"backend": "off"}}
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise _MigrationError(f"{label} config.yml is invalid") from error
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise _MigrationError(f"{label} config.yml must be an object")
    return _strip_legacy_broker(parsed)


def _merge_runtime_config(
    left: Mapping[str, object], right: Mapping[str, object], prefix: str = ""
) -> dict[str, object]:
    merged: dict[str, object] = {}
    for key in sorted(set(left) | set(right)):
        key_path = f"{prefix}.{key}" if prefix else key
        if key not in left:
            merged[key] = right[key]
            continue
        if key not in right:
            merged[key] = left[key]
            continue
        left_value = left[key]
        right_value = right[key]
        if isinstance(left_value, dict) and isinstance(right_value, dict):
            merged[key] = _merge_runtime_config(
                left_value, right_value, key_path
            )
        elif left_value == right_value:
            merged[key] = left_value
        else:
            raise _MigrationError(
                f"OMP settings conflict at {key_path}"
            )
    return merged


def _sqlite_value_digest(value: object) -> object:
    if isinstance(value, bytes):
        return {"bytes": _digest_bytes(value)}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _sqlite_rows_digest(
    connection: sqlite3.Connection, query: str
) -> str:
    rows = [
        [_sqlite_value_digest(value) for value in row]
        for row in connection.execute(query).fetchall()
    ]
    return _digest_json(rows)


def _database_summary(
    path: Path, label: str
) -> tuple[int, str, str, str]:
    if not path.is_file():
        return 0, _digest_json([]), _digest_json([]), _digest_json([])
    try:
        writer = sqlite3.connect(path, timeout=0.05)
        try:
            writer.execute("BEGIN IMMEDIATE")
            writer.rollback()
        finally:
            writer.close()
        connection = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, timeout=0.05
        )
        try:
            if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise _MigrationError(f"{label} agent.db failed quick_check")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            required = {
                "auth_credentials",
                "auth_schema_version",
                "schema_version",
                "settings",
            }
            if not required.issubset(tables):
                raise _MigrationError(f"{label} agent.db schema is incomplete")
            auth_rows = connection.execute(
                "SELECT provider, credential_type, identity_key "
                "FROM auth_credentials "
                "WHERE disabled_cause IS NULL "
                "ORDER BY provider, credential_type, identity_key"
            ).fetchall()
            auth_projection = [
                [
                    provider,
                    credential_type,
                    _digest_bytes((identity_key or "").encode("utf-8")),
                ]
                for provider, credential_type, identity_key in auth_rows
            ]
            settings_digest = _sqlite_rows_digest(
                connection, "SELECT * FROM settings ORDER BY rowid"
            )
            schema_digest = _digest_json(
                {
                    "auth": connection.execute(
                        "SELECT * FROM auth_schema_version ORDER BY rowid"
                    ).fetchall(),
                    "agent": connection.execute(
                        "SELECT * FROM schema_version ORDER BY rowid"
                    ).fetchall(),
                }
            )
            return (
                len(auth_rows),
                _digest_json(auth_projection),
                settings_digest,
                schema_digest,
            )
        finally:
            connection.close()
    except _MigrationError:
        raise
    except sqlite3.Error as error:
        raise _MigrationError(
            f"{label} agent.db is busy or unreadable"
        ) from error


def _session_inventory(root: Path, label: str) -> dict[str, str]:
    sessions = root / "sessions"
    if not sessions.exists():
        return {}
    inventory: dict[str, str] = {}
    for path in sorted(sessions.rglob("*")):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise _MigrationError(f"{label} sessions contain a symlink")
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise _MigrationError(
                f"{label} sessions contain an unsafe file"
            )
        relative = path.relative_to(sessions).as_posix()
        inventory[relative] = _digest_bytes(path.read_bytes())
    return inventory


def _runtime_summary(label: str, root: Path) -> _RuntimeSummary:
    if not root.exists():
        return _RuntimeSummary(
            label,
            root,
            False,
            0,
            _digest_json([]),
            _digest_json([]),
            _digest_json([]),
            {"memory": {"backend": "off"}},
            {},
        )
    _validate_private_runtime(root, label)
    _reject_unsafe_tree(root, label)
    auth_count, auth_digest, db_settings, schema_digest = (
        _database_summary(root / "agent.db", label)
    )
    config = _read_runtime_config(root, label)
    settings_digest = _digest_json(
        {"database": db_settings, "yaml": config}
    )
    return _RuntimeSummary(
        label,
        root,
        True,
        auth_count,
        auth_digest,
        settings_digest,
        schema_digest,
        config,
        _session_inventory(root, label),
    )


def _choose_canonical(
    summaries: Mapping[str, _RuntimeSummary],
) -> str | None:
    existing = [
        profile for profile, summary in summaries.items() if summary.exists
    ]
    if not existing:
        return None
    if len(existing) == 1:
        return existing[0]
    general = summaries["general"]
    helper = summaries["assembly-helper"]
    if general.schema_digest != helper.schema_digest:
        raise _MigrationError("legacy OMP database schemas differ")
    if general.auth_count and helper.auth_count:
        if general.auth_digest != helper.auth_digest:
            raise _MigrationError("legacy OMP authentication identities differ")
        return "general"
    if helper.auth_count:
        return "assembly-helper"
    return "general"


def _merge_session_inventory(
    summaries: Mapping[str, _RuntimeSummary],
) -> dict[str, tuple[str, str]]:
    merged: dict[str, tuple[str, str]] = {}
    for label, summary in summaries.items():
        if not summary.exists:
            continue
        for relative, digest in summary.sessions.items():
            existing = merged.get(relative)
            if existing and existing[1] != digest:
                raise _MigrationError(
                    f"OMP Session conflict at {relative}"
                )
            merged[relative] = (label, digest)
    return merged
def _is_initialized_empty_global(
    summary: _RuntimeSummary,
    marker: Mapping[str, object] | None,
) -> bool:
    if not summary.exists or marker is None:
        return False
    allowed_names = {
        ".cap-shared-runtime.json",
        "config.yml",
        "mcp.json",
        "sessions",
    }
    if {
        path.name for path in summary.root.iterdir()
    } - allowed_names:
        return False
    return (
        marker.get("version") == 2
        and marker.get("canonical") is None
        and marker.get("migration_complete") is True
        and marker.get("session_files", 0) == 0
        and summary.auth_count == 0
        and not summary.sessions
        and summary.config == {"memory": {"backend": "off"}}
    )




def _migration_plan(
    args: argparse.Namespace,
) -> tuple[
    dict[str, object],
    dict[str, _RuntimeSummary],
    str | None,
    dict[str, object],
    dict[str, tuple[str, str]],
]:
    project_root = _agent_home_root(args)
    if project_root.exists():
        _assert_managed_path(
            project_root.parent, project_root, "agent home root"
        )
    source = _runtime_summary(
        "project-shared", _project_shared_omp_home(args)
    )
    target_root = _agent_home_dir(args)
    target = _runtime_summary("global", target_root)
    marker_payload: dict[str, object] | None = None
    if target.exists:
        marker = _shared_runtime_marker(args)
        if not marker.is_file():
            raise _MigrationError(
                "global OMP runtime exists without a migration marker"
            )
        try:
            marker_payload = json.loads(
                marker.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise _MigrationError(
                "global OMP migration marker is invalid"
            ) from error
        if (
            marker_payload.get("version") != 2
            or marker_payload.get("runtime_id") != _omp_runtime_id(args)
        ):
            raise _MigrationError(
                "global OMP migration marker does not match runtime id"
            )
    summaries = {"project-shared": source, "global": target}
    if target.exists and not source.exists:
        public = {
            "status": "already-global",
            "runtime_id": _omp_runtime_id(args),
            "source": {"exists": False},
            "target": {
                "exists": True,
                "auth_entries": target.auth_count,
                "auth_digest": target.auth_digest,
                "settings_digest": target.settings_digest,
                "schema_digest": target.schema_digest,
                "session_files": len(target.sessions),
            },
            "session_files": len(target.sessions),
            "writes_planned": False,
        }
        return public, summaries, "global", target.config, {}
    if source.exists and target.exists:
        target_has_database = (target.root / "agent.db").is_file()
        if target_has_database:
            if source.schema_digest != target.schema_digest:
                raise _MigrationError(
                    "project and global OMP database schemas differ"
                )
            if (
                source.auth_count
                and target.auth_count
                and source.auth_digest != target.auth_digest
            ):
                raise _MigrationError(
                    "project and global OMP authentication identities differ"
                )
            canonical = (
                "global" if target.auth_count else "project-shared"
            )
        elif _is_initialized_empty_global(target, marker_payload):
            canonical = "project-shared"
        else:
            raise _MigrationError(
                "global OMP runtime is incomplete without agent.db"
            )
        config = _merge_runtime_config(target.config, source.config)
    elif source.exists:
        canonical = "project-shared"
        config = source.config
    else:
        canonical = None
        config = {"memory": {"backend": "off"}}
    config = _strip_legacy_broker(config)
    sessions = _merge_session_inventory(summaries)
    public = {
        "status": "ready",
        "runtime_id": _omp_runtime_id(args),
        "source": {
            "exists": source.exists,
            "auth_entries": source.auth_count,
            "auth_digest": source.auth_digest,
            "settings_digest": source.settings_digest,
            "schema_digest": source.schema_digest,
            "session_files": len(source.sessions),
        },
        "target": {
            "exists": target.exists,
            "auth_entries": target.auth_count,
            "auth_digest": target.auth_digest,
            "settings_digest": target.settings_digest,
            "schema_digest": target.schema_digest,
            "session_files": len(target.sessions),
        },
        "canonical": canonical,
        "merged_settings_digest": _digest_json(config),
        "session_files": len(sessions),
        "writes_planned": True,
    }
    return public, summaries, canonical, config, sessions


_MIGRATION_SKIP_NAMES = {
    ".cap-rendered",
    "config.yml",
    "config.yml.lock",
    "home",
    "mcp.json",
    "sessions",
    "skills",
    "system-prompt.md",
    "terminal-sessions",
}


def _sqlite_backup(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(
        f"file:{source}?mode=ro", uri=True, timeout=0.1
    )
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    target.chmod(0o600)


def _copy_runtime_payload(source: Path, target: Path) -> None:
    target.mkdir(mode=0o700)
    for entry in sorted(source.iterdir(), key=lambda item: item.name):
        if (
            entry.name in _MIGRATION_SKIP_NAMES
            or entry.name.endswith("-wal")
            or entry.name.endswith("-shm")
            or entry.name.endswith(".lock")
        ):
            continue
        destination = target / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination)
        elif entry.suffix == ".db":
            _sqlite_backup(entry, destination)
        elif entry.is_file():
            shutil.copy2(entry, destination)
        else:
            raise _MigrationError("legacy OMP runtime contains unsafe state")


def _write_runtime_config(
    target: Path, config: Mapping[str, object]
) -> None:
    path = target / "config.yml"
    path.write_text(
        yaml.safe_dump(
            dict(config),
            allow_unicode=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _write_shared_mcp_policy(target: Path) -> None:
    policy = {
        "mcpServers": {},
        "disabledServers": list(OMP_AMBIENT_MCP_DENYLIST),
    }
    path = target / "mcp.json"
    path.write_text(
        json.dumps(policy, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _validate_shared_mcp_policy(target: Path) -> None:
    path = target / "mcp.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _MigrationError(
            "shared OMP MCP denylist is missing or invalid"
        ) from error
    expected = {
        "mcpServers": {},
        "disabledServers": list(OMP_AMBIENT_MCP_DENYLIST),
    }
    if payload != expected:
        raise _MigrationError("shared OMP MCP denylist drifted")


def _copy_merged_sessions(
    summaries: Mapping[str, _RuntimeSummary],
    sessions: Mapping[str, tuple[str, str]],
    target: Path,
) -> None:
    session_root = target / "sessions"
    session_root.mkdir(mode=0o700)
    for relative, (profile, expected_digest) in sorted(sessions.items()):
        source = summaries[profile].root / "sessions" / relative
        if _digest_bytes(source.read_bytes()) != expected_digest:
            raise _MigrationError(
                "legacy OMP Session changed during migration"
            )
        destination = session_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(source, destination)


def _backup_legacy_runtime(
    summaries: Mapping[str, _RuntimeSummary], backup: Path
) -> None:
    backup.mkdir(parents=True, mode=0o700)
    for profile, summary in summaries.items():
        if not summary.exists:
            continue
        destination = backup / profile
        _copy_runtime_payload(summary.root, destination)
        _write_runtime_config(destination, summary.config)
        _copy_merged_sessions(
            summaries,
            {
                relative: (profile, digest)
                for relative, digest in summary.sessions.items()
            },
            destination,
        )


def _apply_omp_runtime_migration(
    args: argparse.Namespace,
    public: dict[str, object],
    summaries: Mapping[str, _RuntimeSummary],
    canonical: str | None,
    config: Mapping[str, object],
    sessions: Mapping[str, tuple[str, str]],
) -> dict[str, object]:
    if public["status"] == "already-global":
        _write_shared_mcp_policy(_agent_home_dir(args))
        return {**public, "mcp_policy_refreshed": True}
    project_root = _agent_home_root(args)
    project_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    project_root.chmod(0o700)
    backup = _migration_backup_root(args)
    if backup.exists():
        raise _MigrationError("OMP migration backup already exists")
    target = _agent_home_dir(args)
    target_parent = target.parent
    target_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for private in (
        _runtime_real_home(args) / ".cap-user-state",
        _runtime_real_home(args) / ".cap-user-state" / "runtimes",
        target_parent,
    ):
        private.mkdir(parents=True, exist_ok=True, mode=0o700)
        private.chmod(0o700)
        _validate_private_runtime(private, "global CAP state directory")
    stage = target_parent / f".omp-stage-{os.getpid()}-{time.time_ns()}"
    old_target = target_parent / f".omp-old-{os.getpid()}-{time.time_ns()}"
    target_was_moved = False
    try:
        _backup_legacy_runtime(summaries, backup)
        if canonical is None:
            stage.mkdir(mode=0o700)
        else:
            _copy_runtime_payload(summaries[canonical].root, stage)
        _write_runtime_config(stage, config)
        _write_shared_mcp_policy(stage)
        _copy_merged_sessions(summaries, sessions, stage)
        marker = {
            "version": 2,
            "runtime_id": _omp_runtime_id(args),
            "canonical": canonical,
            "session_files": len(sessions),
            "settings_digest": _digest_json(config),
            "source_digest": _digest_json(
                {
                    label: {
                        "auth": summary.auth_digest,
                        "settings": summary.settings_digest,
                        "schema": summary.schema_digest,
                    }
                    for label, summary in summaries.items()
                    if summary.exists
                }
            ),
            "migration_complete": True,
        }
        (stage / ".cap-shared-runtime.json").write_text(
            json.dumps(marker, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _runtime_summary("staged global runtime", stage)
        if target.exists():
            os.rename(target, old_target)
            target_was_moved = True
        try:
            os.rename(stage, target)
        except BaseException:
            if target_was_moved:
                os.rename(old_target, target)
                target_was_moved = False
            raise
        if old_target.exists():
            shutil.rmtree(old_target)
            target_was_moved = False
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        if target_was_moved and old_target.exists() and not target.exists():
            os.rename(old_target, target)
        if backup.exists() and not target.exists():
            shutil.rmtree(backup)
        raise
    return {
        **public,
        "status": "migrated-global",
        "writes_planned": False,
        "backup_created": True,
    }


def _safe_remove_tree(root: Path, candidate: Path, label: str) -> bool:
    if not candidate.exists() and not candidate.is_symlink():
        return False
    _assert_managed_path(root, candidate, label)
    _reject_unsafe_tree(candidate, label)
    shutil.rmtree(candidate)
    return True


def _cleanup_legacy_omp_runtime(args: argparse.Namespace) -> dict[str, object]:
    marker = _shared_runtime_marker(args)
    if not marker.is_file():
        raise _MigrationError(
            "global OMP runtime is not verified for cleanup"
        )
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _MigrationError("global OMP marker is invalid") from error
    if (
        payload.get("version") != 2
        or payload.get("runtime_id") != _omp_runtime_id(args)
    ):
        raise _MigrationError("global OMP marker does not match runtime id")
    root = _agent_home_root(args)
    removed: list[str] = []
    for label, path in (
        ("project-shared-runtime", _project_shared_omp_home(args)),
        ("project-render-cache", _project_render_root(args)),
        ("migration-backup", _migration_backup_root(args)),
    ):
        if _safe_remove_tree(root, path, label):
            removed.append(label)
    return {
        "status": "cleaned-project-state",
        "runtime_id": _omp_runtime_id(args),
        "removed": removed,
    }


def _migrate_omp_runtime(args: argparse.Namespace) -> int:
    try:
        if args.cleanup:
            payload = _cleanup_legacy_omp_runtime(args)
        else:
            public, summaries, canonical, config, sessions = (
                _migration_plan(args)
            )
            payload = (
                _apply_omp_runtime_migration(
                    args,
                    public,
                    summaries,
                    canonical,
                    config,
                    sessions,
                )
                if args.apply
                else public
            )
    except (_MigrationError, OSError) as error:
        print(f"OMP runtime 迁移失败：{error}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _require_shared_runtime_ready(args: argparse.Namespace) -> None:
    shared = _agent_home_dir(args)
    marker = _shared_runtime_marker(args)
    if not shared.is_dir() or not marker.is_file():
        if _project_shared_omp_home(args).exists():
            raise _MigrationError(
                "project OMP runtime requires `cap migrate-omp-runtime --apply`"
            )
        raise _MigrationError(
            "global OMP runtime requires `cap migrate-omp-runtime --apply`"
        )
    _assert_managed_path(
        _runtime_real_home(args), shared, "global OMP runtime"
    )
    _validate_private_runtime(shared, "global OMP runtime")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _MigrationError(
            "global OMP migration marker is invalid"
        ) from error
    if (
        payload.get("version") != 2
        or payload.get("runtime_id") != _omp_runtime_id(args)
        or payload.get("migration_complete") is not True
    ):
        raise _MigrationError(
            "global OMP migration is incomplete or mismatched"
        )
    _validate_shared_mcp_policy(shared)


def _passthrough(values: list[str]) -> list[str]:
    return values


def _profile_args(args: argparse.Namespace) -> list[str]:
    base = _base_args(args)
    command = args.profile_tool_command
    if command in {"list", "lock"}:
        return [*base, command]
    if command == "verify":
        return [*base, command, *_binding_args(args)]
    if command == "explain":
        return [*base, "explain", "--profile", args.profile]
    if command == "materialize":
        return [
            *base,
            "materialize",
            "--client",
            args.cli,
            "--profile",
            args.profile,
            "--output",
            args.output,
            *_binding_args(args),
        ]
    if command == "launch":
        receipt = Path(args.receipt).expanduser() if args.receipt else Path(
            _run_path(args, "receipt.json")
        )
        receipt.parent.mkdir(parents=True, exist_ok=True)
        return [
            *base,
            "launch",
            "--client",
            args.cli,
            "--profile",
            args.profile,
            "--auth-root",
            str(Path(args.auth_root).expanduser()),
            "--receipt",
            str(receipt),
            "--workdir",
            str(_workdir(args)),
            *_binding_args(args),
            "--",
            *_passthrough(args.client_args),
        ]
    if command == "run":
        state = args.state or _run_path(args, "state")
        Path(state).mkdir(parents=True, exist_ok=True)
        return [
            *base,
            "run",
            "--client",
            args.cli,
            "--profile",
            args.profile,
            "--auth-root",
            str(Path(args.auth_root).expanduser()),
            "--state",
            state,
            "--workdir",
            str(_workdir(args)),
            *_binding_args(args),
            "--",
            *_passthrough(args.client_args),
        ]
    raise AssertionError(f"unsupported command: {command}")




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
    available = {item for item in profiles if isinstance(item, str)}
    return [name for name in RUNNABLE_PROFILES if name in available]


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
            preview: dict[str, object] = {
                "client": args.cli,
                "files": files,
                "tree_hash": tree_hash,
            }
            if args.cli == "omp":
                try:
                    (
                        generation,
                        portable_hash,
                        effective_hash,
                        skill_names,
                    ) = _materialize_profile_generation(args, env)
                except _MigrationError as error:
                    print(
                        f"effective render 失败：{error}",
                        file=sys.stderr,
                    )
                    return None
                manifest = json.loads(
                    (generation / ".cap-generation.json").read_text(
                        encoding="utf-8"
                    )
                )
                preview.update(
                    {
                        "runtime_id": _omp_runtime_id(args),
                        "global_runtime_root": str(
                            _agent_home_dir(args)
                        ),
                        "global_generation": str(generation),
                        "portable_tree_hash": portable_hash,
                        "effective_render_hash": effective_hash,
                        "project_source_context": manifest[
                            "source_context"
                        ],
                        "project_source_digest": manifest[
                            "source_digest"
                        ],
                        "skills": skill_names,
                        "fixed_flags": [
                            "--no-extensions",
                            "--no-rules",
                        ],
                    }
                )
            return preview
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


def _tree_digest(root: Path, *, exclude: set[str] | None = None) -> str:
    excluded = exclude or set()
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise _MigrationError("profile generation contains a symlink")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if stat.S_ISDIR(info.st_mode):
            digest.update(b"d\0")
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            digest.update(b"f\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        else:
            raise _MigrationError(
                "profile generation contains an unsafe file"
            )
    return f"sha256:{digest.hexdigest()}"


def _deep_overlay(
    base: Mapping[str, object], override: Mapping[str, object]
) -> dict[str, object]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_overlay(existing, value)
        else:
            merged[key] = value
    return merged


def _effective_config_template(
    portable_config: Mapping[str, object],
    skill_names: list[str],
) -> dict[str, object]:
    return _deep_overlay(
        portable_config,
        {
            "memory": {"backend": "off"},
            "mcp": {"enableProjectConfig": False},
            "skills": {
                "customDirectories": [
                    "<PROFILE_GENERATION>/skills"
                ],
                "includeSkills": skill_names,
                "enableCodexUser": False,
                "enableClaudeUser": False,
                "enableClaudeProject": False,
                "enablePiUser": False,
                "enablePiProject": False,
                "enableAgentsUser": False,
                "enableAgentsProject": False,
            },
        },
    )


def _replace_generation_placeholder(
    value: object, generation: Path
) -> object:
    if isinstance(value, str):
        return value.replace(
            "<PROFILE_GENERATION>", str(generation)
        )
    if isinstance(value, list):
        return [
            _replace_generation_placeholder(item, generation)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _replace_generation_placeholder(item, generation)
            for key, item in value.items()
        }
    return value


def _read_portable_config(rendered: Path) -> dict[str, object]:
    path = rendered / "config.yml"
    if not path.is_file():
        return {}
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise _MigrationError(
            "portable OMP config is invalid"
        ) from error
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise _MigrationError(
            "portable OMP config must be an object"
        )
    return parsed


def _generation_source_context(
    args: argparse.Namespace, portable_hash: str
) -> tuple[dict[str, object], str]:
    binding_path = (
        Path(args.binding_dir).expanduser()
        / f"{args.profile}.binding.json"
    )
    lock_path = Path(args.project).expanduser() / ".cap" / "lock.json"
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        adapter_version = lock["clients"]["omp"]["adapter_version"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise _MigrationError(
            "current project binding/lock context is invalid"
        ) from error
    context = {
        "profile": args.profile,
        "layer_digest": binding.get("layer_digest"),
        "effective_digest": binding.get("effective_digest"),
        "portable_tree_hash": portable_hash,
        "adapter_version": adapter_version,
    }
    if not all(
        isinstance(context[key], (str, int))
        for key in (
            "layer_digest",
            "effective_digest",
            "portable_tree_hash",
            "adapter_version",
        )
    ):
        raise _MigrationError(
            "current project binding/adapter context is incomplete"
        )
    return context, _digest_json(context)


def _verify_profile_generation(
    generation: Path,
    profile: str,
    portable_hash: str,
    effective_hash: str,
    source_context: Mapping[str, object],
    source_digest: str,
) -> dict[str, object]:
    manifest = generation / ".cap-generation.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _MigrationError(
            "profile generation manifest is invalid"
        ) from error
    expected = {
        "version": 2,
        "profile": profile,
        "portable_tree_hash": portable_hash,
        "effective_render_hash": effective_hash,
        "source_context": dict(source_context),
        "source_digest": source_digest,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise _MigrationError(
                "profile generation metadata drifted"
            )
    content_digest = _tree_digest(
        generation, exclude={".cap-generation.json"}
    )
    if payload.get("content_digest") != content_digest:
        raise _MigrationError(
            "profile generation content drifted"
        )
    return payload


def _materialize_profile_generation(
    args: argparse.Namespace,
    env: dict[str, str],
) -> tuple[Path, str, str, list[str]]:
    with tempfile.TemporaryDirectory(
        prefix=f"cap-render-{args.profile}-omp-"
    ) as temporary:
        completed = subprocess.run(
            [
                *_base_args(args),
                "materialize",
                "--client",
                "omp",
                "--profile",
                args.profile,
                "--output",
                temporary,
                *_binding_args(args),
            ],
            capture_output=True,
            check=False,
            env=env,
            text=True,
        )
        if completed.returncode != 0:
            print(
                completed.stderr.strip() or completed.stdout.strip(),
                file=sys.stderr,
            )
            raise SystemExit(completed.returncode)
        try:
            portable_hash = json.loads(completed.stdout)["tree_hash"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise _MigrationError(
                "OMP materialize output has no tree_hash"
            ) from error
        if not isinstance(portable_hash, str):
            raise _MigrationError(
                "OMP materialize tree_hash must be a string"
            )
        rendered = Path(temporary)
        skills_root = rendered / "skills"
        skill_names = (
            sorted(
                path.name
                for path in skills_root.iterdir()
                if path.is_dir() and not path.is_symlink()
            )
            if skills_root.is_dir()
            else []
        )
        config_template = _effective_config_template(
            _read_portable_config(rendered), skill_names
        )
        fixed_launch = {
            "extension": "explicit",
            "no_extensions": True,
            "no_rules": True,
            "skills": skill_names,
        }
        source_context, source_digest = _generation_source_context(
            args, portable_hash
        )
        effective_hash = _digest_json(
            {
                "version": 2,
                "source_context": source_context,
                "source_digest": source_digest,
                "config": config_template,
                "launch": fixed_launch,
            }
        )
        generation = (
            _profile_render_parent(args)
            / effective_hash.removeprefix("sha256:")
        )
        if generation.exists():
            _verify_profile_generation(
                generation,
                args.profile,
                portable_hash,
                effective_hash,
                source_context,
                source_digest,
            )
            return generation, portable_hash, effective_hash, skill_names
        parent = generation.parent
        for private in (
            _runtime_real_home(args) / ".cap-user-state",
            _runtime_real_home(args) / ".cap-user-state" / "renders",
            parent,
        ):
            private.mkdir(parents=True, exist_ok=True, mode=0o700)
            private.chmod(0o700)
            _validate_private_runtime(private, "global CAP render directory")
        _assert_managed_path(
            _runtime_real_home(args), parent, "global render CAS"
        )
        stage = parent / (
            f".stage-{os.getpid()}-{time.time_ns()}"
        )
        try:
            shutil.copytree(rendered, stage)
            actual_config = _replace_generation_placeholder(
                config_template, generation
            )
            config_path = stage / "config.yml"
            config_path.write_text(
                yaml.safe_dump(
                    actual_config,
                    allow_unicode=True,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            config_path.chmod(0o600)
            extension = stage / "extension"
            extension.mkdir(mode=0o700)
            mcp_source = stage / "mcp.json"
            if mcp_source.is_file():
                shutil.copy2(
                    mcp_source, extension / ".mcp.json"
                )
            content_digest = _tree_digest(stage)
            manifest = {
                "version": 2,
                "profile": args.profile,
                "portable_tree_hash": portable_hash,
                "effective_render_hash": effective_hash,
                "source_context": source_context,
                "source_digest": source_digest,
                "content_digest": content_digest,
                "skills": skill_names,
            }
            (stage / ".cap-generation.json").write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            try:
                os.rename(stage, generation)
            except OSError:
                if not generation.exists():
                    raise
                shutil.rmtree(stage)
                _verify_profile_generation(
                    generation,
                    args.profile,
                    portable_hash,
                    effective_hash,
                    source_context,
                    source_digest,
                )
        except BaseException:
            if stage.exists():
                shutil.rmtree(stage)
            raise
        return generation, portable_hash, effective_hash, skill_names


def _omp_command(
    generation: Path,
    skill_names: list[str],
    forwarded: list[str],
) -> list[str]:
    executable = shutil.which("omp") or "omp"
    prompt = (
        (generation / "system-prompt.md")
        .read_text(encoding="utf-8")
        .strip()
        + "\n"
    )
    skill_args = (
        ["--skills", ",".join(skill_names)]
        if skill_names
        else ["--no-skills"]
    )
    return [
        executable,
        "--config",
        str(generation / "config.yml"),
        "--append-system-prompt",
        prompt,
        "--extension",
        str(generation / "extension"),
        "--no-extensions",
        *skill_args,
        "--no-rules",
        *forwarded,
    ]


def _agent_home_env(
    base_env: dict[str, str],
    agent_home: Path,
    generation: Path,
    real_home: Path,
) -> dict[str, str]:
    env = base_env.copy()
    for name in AMBIENT_CONFIG_ENV:
        env.pop(name, None)
    for name in OMP_AMBIENT_AUTH_ENV | {
        candidate
        for candidate in env
        if _is_ambient_credential_name(candidate)
    }:
        env[name] = ""
    env.pop("OMP_AUTH_BROKER_URL", None)
    env.pop("OMP_AUTH_BROKER_TOKEN", None)
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    env["PI_AUTH_NO_BORROW"] = "1"
    env.update(
        {
            "HOME": str(real_home),
            "OMP_PROFILE": "default",
            "PI_CODING_AGENT_DIR": str(agent_home),
            "PI_CONFIG_DIR": str(agent_home),
            "PI_CONFIG_FILES": str(
                generation / "config.yml"
            ),
            "PI_PROFILE": "default",
        }
    )
    return env


def _write_receipt(
    args: argparse.Namespace,
    receipt: Path,
    return_code: int,
    portable_hash: str,
    effective_hash: str,
    agent_home: Path,
    generation: Path,
) -> None:
    binding_path = (
        Path(args.binding_dir).expanduser()
        / f"{args.profile}.binding.json"
    )
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    manifest = json.loads(
        (generation / ".cap-generation.json").read_text(encoding="utf-8")
    )
    payload = {
        "version": 4,
        "client": args.cli,
        "profile": args.profile,
        "runtime_id": _omp_runtime_id(args),
        "global_runtime_root": str(agent_home),
        "global_generation": str(generation),
        "project_root": str(Path(args.project).expanduser().absolute()),
        "project_source_context": manifest["source_context"],
        "project_source_digest": manifest["source_digest"],
        "base_digest": binding["base_digest"],
        "layer_digest": binding["layer_digest"],
        "effective_digest": binding["effective_digest"],
        "portable_tree_hash": portable_hash,
        "effective_render_hash": effective_hash,
        "workdir": str(_workdir(args)),
        "exit_code": return_code,
        "forwarded_argument_count": len(args.client_args),
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_omp_agent_home(
    args: argparse.Namespace, env: dict[str, str]
) -> int:
    try:
        _require_shared_runtime_ready(args)
        (
            generation,
            portable_hash,
            effective_hash,
            skill_names,
        ) = _materialize_profile_generation(args, env)
    except _MigrationError as error:
        print(f"持久 OMP 启动失败：{error}", file=sys.stderr)
        return 2
    agent_home = _agent_home_dir(args)
    receipt = (
        Path(args.receipt).expanduser()
        if getattr(args, "receipt", None)
        else Path(_run_path(args, "receipt.json"))
    )
    workdir = _workdir(args)
    real_home = Path(
        getattr(
            args,
            "_real_home",
            os.environ.get("HOME") or Path.home(),
        )
    )
    completed = subprocess.run(
        _omp_command(
            generation,
            skill_names,
            _passthrough(args.client_args),
        ),
        cwd=str(workdir),
        env=_agent_home_env(
            env, agent_home, generation, real_home
        ),
        check=False,
    )
    verified = subprocess.run(
        [
            *_base_args(args),
            "verify",
            *_binding_args(args),
        ],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    if verified.returncode != 0:
        print(
            verified.stderr.strip() or verified.stdout.strip(),
            file=sys.stderr,
        )
        return verified.returncode
    _write_receipt(
        args,
        receipt,
        completed.returncode,
        portable_hash,
        effective_hash,
        agent_home,
        generation,
    )
    return (
        completed.returncode
        if completed.returncode >= 0
        else 128 + abs(completed.returncode)
    )


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
    if args.command == "migrate-omp-runtime":
        return _migrate_omp_runtime(args)
    _ensure_capability_store_dirs(Path(args.project).expanduser().resolve())
    if getattr(args, "profile_tool_command", None) == "verify":
        report = _skill_metadata_report(Path(args.project).expanduser().resolve())
        if report["standard_conformance"] != "ok":
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2
    real_home = Path(args.home).expanduser().resolve(strict=True)
    if not real_home.is_dir():
        parser.error(f"--home 必须是目录: {real_home}")
    args._real_home = str(real_home)
    env = os.environ.copy()
    env["HOME"] = str(real_home)
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
