#!/usr/bin/env python3
"""Run a bounded LLM-as-a-Verifier evaluation and emit redacted evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional, Sequence


REQUEST_VERSION = "agent-assembly.verifier-request/v1"
EVIDENCE_VERSION = "agent-assembly.verifier-evidence/v1"
VERIFIER_REPOSITORY = "https://github.com/llm-as-a-verifier/llm-as-a-verifier"
VERIFIER_ARTIFACT = "llm_verifier-0.2.0-py3-none-any.whl"
VERIFIER_ARTIFACT_SHA256 = (
    "5d1678c93d19874acd15999026117371c73367e3faac1712affe6dd7f38303af")
ROOT = Path(__file__).resolve().parents[1]
OMP_EXTENSION = ROOT / "evaluations" / "llm-verifier" / "omp-verifier.ts"
OMP_CONFIG = ROOT / "evaluations" / "llm-verifier" / "omp-no-fallback.yml"
OMP_RESULT_VERSION = "agent-assembly.omp-completion/v1"
OMP_RESULT_PREFIX = "__AGENT_ASSEMBLY_OMP_RESULT__"
OMP_TIMEOUT_SECONDS = 90
SCORE_A_PATTERN = re.compile(r"<score_A>\s*([A-T])\s*</score_A>")
SCORE_B_PATTERN = re.compile(r"<score_B>\s*([A-T])\s*</score_B>")


class RequestError(ValueError):
    pass


class OmpBackendError(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    data = value if isinstance(value, bytes) else canonical_json(value)
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def exact_keys(value: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RequestError(f"{location} contains unsupported fields: {unknown}")


def require_text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RequestError(f"{location} must be a non-empty string")
    return value


def require_id(value: Any, location: str) -> str:
    identifier = require_text(value, location)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identifier):
        raise RequestError(
            f"{location} must use lowercase letters, digits, hyphens, and underscores")
    return identifier


def validate_request(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise RequestError("request must be a JSON object")
    exact_keys(document, {
        "schema_version", "run_id", "problem", "candidates", "criteria",
        "backend", "parameters",
    }, "request")
    if document.get("schema_version") != REQUEST_VERSION:
        raise RequestError(f"schema_version must be {REQUEST_VERSION!r}")
    run_id = require_text(document.get("run_id"), "run_id")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", run_id):
        raise RequestError("run_id must use lowercase letters, digits, and hyphens")
    require_text(document.get("problem"), "problem")

    candidates = document.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise RequestError("candidates must contain at least two entries")
    candidate_ids = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise RequestError(f"candidates[{index}] must be an object")
        exact_keys(candidate, {"id", "trajectory"}, f"candidates[{index}]")
        candidate_ids.append(require_id(candidate.get("id"),
                                        f"candidates[{index}].id"))
        require_text(candidate.get("trajectory"),
                     f"candidates[{index}].trajectory")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise RequestError("candidate ids must be unique")

    criteria = document.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise RequestError("criteria must contain at least one entry")
    for index, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            raise RequestError(f"criteria[{index}] must be an object")
        exact_keys(criterion, {"id", "name", "description"},
                   f"criteria[{index}]")
        require_id(criterion.get("id"), f"criteria[{index}].id")
        for field in ("name", "description"):
            require_text(criterion.get(field), f"criteria[{index}].{field}")

    backend = document.get("backend")
    if not isinstance(backend, dict):
        raise RequestError("backend must be an object")
    exact_keys(backend, {"kind", "model"}, "backend")
    if backend.get("kind") not in ("fixture", "environment", "omp"):
        raise RequestError(
            "backend.kind must be 'fixture', 'environment', or 'omp'")
    model = require_text(backend.get("model"), "backend.model")
    if backend["kind"] == "omp" and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}/"
            r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,191}", model):
        raise RequestError(
            "backend.model must be an explicit OMP provider/model selector")

    parameters = document.get("parameters")
    if not isinstance(parameters, dict):
        raise RequestError("parameters must be an object")
    exact_keys(parameters, {"n_evaluations", "pivots", "seed"}, "parameters")
    n_evaluations = parameters.get("n_evaluations")
    if (not isinstance(n_evaluations, int) or n_evaluations < 2
            or n_evaluations % 2):
        raise RequestError("parameters.n_evaluations must be an even integer >= 2")
    if not isinstance(parameters.get("pivots"), int) or parameters["pivots"] < 1:
        raise RequestError("parameters.pivots must be an integer >= 1")
    if not isinstance(parameters.get("seed"), int):
        raise RequestError("parameters.seed must be an integer")
    return document


class FixtureModels:
    @staticmethod
    def generate_content(*, contents, **_kwargs):
        prompt = contents[0].parts[0].text
        trace_a = prompt.split("**Trajectory A:**\n", 1)[1].split(
            "\n\n**Trajectory B:**", 1)[0]
        trace_b = prompt.split("**Trajectory B:**\n", 1)[1].split(
            "\n\n**Rating Scale:**", 1)[0]

        def token(trace: str) -> str:
            if "EXPECTED_PASS" in trace:
                return "A"
            if "EXPECTED_REJECT" in trace:
                return "T"
            return "K"

        text = (f"<score_A> {token(trace_a)} </score_A>\n"
                f"<score_B> {token(trace_b)} </score_B>")
        usage = SimpleNamespace(
            prompt_token_count=100, cached_content_token_count=0,
            candidates_token_count=10, thoughts_token_count=0,
        )
        candidate = SimpleNamespace(logprobs_result=None)
        return SimpleNamespace(
            text=text, candidates=[candidate], usage_metadata=usage)


class FixtureClient:
    def __init__(self):
        self.models = FixtureModels()


def _omp_usage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OmpBackendError("invalid OMP usage")
    result = {}
    for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens"):
        item = value.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise OmpBackendError("invalid OMP usage")
        result[key] = item
    cost = value.get("cost")
    if not isinstance(cost, dict):
        raise OmpBackendError("invalid OMP usage")
    total_cost = cost.get("total")
    if (not isinstance(total_cost, (int, float)) or isinstance(total_cost, bool)
            or not math.isfinite(total_cost) or total_cost < 0):
        raise OmpBackendError("invalid OMP usage")
    result["cost"] = {"total": float(total_cost)}
    return result


class OmpModels:
    def __init__(self, requested_model: str, command: Sequence[str]):
        if not command or any(not part for part in command):
            raise OmpBackendError("OMP command is empty")
        self.requested_model = requested_model
        self.command = list(command)
        self.serving_models: set[str] = set()
        self.reported_cost_usd = 0.0

    def generate_content(self, *, contents, model, **_kwargs):
        if model != self.requested_model:
            raise OmpBackendError("verifier changed the requested OMP model")
        try:
            prompt = contents[0].parts[0].text
        except (AttributeError, IndexError, TypeError) as error:
            raise OmpBackendError("verifier prompt is unavailable") from error
        if not isinstance(prompt, str) or not prompt:
            raise OmpBackendError("verifier prompt is unavailable")

        request = {
            "schema_version": OMP_RESULT_VERSION,
            "model": self.requested_model,
            "prompt": prompt,
            "max_tokens": 512,
        }
        with tempfile.TemporaryDirectory(prefix="agent-assembly-omp-") as temp_dir:
            request_path = Path(temp_dir) / "request.json"
            request_path.write_text(
                json.dumps(request, ensure_ascii=False), encoding="utf-8")
            request_path.chmod(0o600)
            invocation = [
                *self.command,
                "-p", "--mode", "text", "--no-tools", "--no-extensions",
                "-e", str(OMP_EXTENSION), "--no-skills", "--no-rules",
                "--no-session", "--no-title", "--config", str(OMP_CONFIG),
                "--model", self.requested_model,
                "--max-time", f"{OMP_TIMEOUT_SECONDS}s",
                f"/agent-assembly-verifier {request_path}",
            ]
            try:
                completed = subprocess.run(
                    invocation,
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    capture_output=True,
                    encoding="utf-8",
                    timeout=OMP_TIMEOUT_SECONDS,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise OmpBackendError("OMP command failed") from error

        if completed.returncode != 0:
            raise OmpBackendError("OMP command failed")
        if "retry_fallback_applied" in (
                f"{completed.stdout}\n{completed.stderr}"):
            raise OmpBackendError("OMP model fallback was observed")
        payloads = [
            line[len(OMP_RESULT_PREFIX):]
            for line in completed.stdout.splitlines()
            if line.startswith(OMP_RESULT_PREFIX)
        ]
        if len(payloads) != 1:
            raise OmpBackendError("OMP result is missing or ambiguous")
        try:
            result = json.loads(payloads[0])
        except json.JSONDecodeError as error:
            raise OmpBackendError("OMP result is malformed") from error
        if not isinstance(result, dict):
            raise OmpBackendError("OMP result is malformed")
        if set(result) != {
                "schema_version", "requested_model", "model", "stop_reason",
                "usage", "text"}:
            raise OmpBackendError("OMP result fields are invalid")
        if result.get("schema_version") != OMP_RESULT_VERSION:
            raise OmpBackendError("OMP result version is unsupported")
        if result.get("requested_model") != self.requested_model:
            raise OmpBackendError("OMP requested model does not match")
        if result.get("model") != self.requested_model:
            raise OmpBackendError("OMP serving model does not match")
        if result.get("stop_reason") != "stop":
            raise OmpBackendError("OMP completion did not stop normally")
        raw_text = result.get("text")
        if not isinstance(raw_text, str):
            raise OmpBackendError("OMP completion returned an invalid literal score")
        scores_a = SCORE_A_PATTERN.findall(raw_text)
        scores_b = SCORE_B_PATTERN.findall(raw_text)
        if len(scores_a) != 1 or len(scores_b) != 1:
            raise OmpBackendError("OMP completion returned an invalid literal score")
        text = (f"<score_A> {scores_a[0]} </score_A>\n"
                f"<score_B> {scores_b[0]} </score_B>")
        usage = _omp_usage(result.get("usage"))
        self.serving_models.add(result["model"])
        self.reported_cost_usd += usage["cost"]["total"]

        metadata = SimpleNamespace(
            prompt_token_count=usage["input"] + usage["cacheRead"],
            cached_content_token_count=usage["cacheRead"],
            candidates_token_count=usage["output"],
            thoughts_token_count=0,
        )
        candidate = SimpleNamespace(logprobs_result=None)
        return SimpleNamespace(
            text=text, candidates=[candidate], usage_metadata=metadata)


class OmpClient:
    def __init__(self, requested_model: str, command: Sequence[str]):
        self.models = OmpModels(requested_model, command)


def run_evaluation(document: dict[str, Any], cache: Path,
                   omp_command: Sequence[str]) -> dict[str, Any]:
    import llm_verifier

    candidates = document["candidates"]
    backend = document["backend"]
    parameters = document["parameters"]
    request_sha256 = digest(document)
    effective_cache = cache.with_name(
        f"{cache.stem}-{request_sha256}{cache.suffix or '.json'}")
    before_cache = file_digest(effective_cache)
    before_usage = llm_verifier.token_usage()
    if backend["kind"] == "fixture":
        client = FixtureClient()
    elif backend["kind"] == "omp":
        client = OmpClient(backend["model"], omp_command)
    else:
        client = None
    result = llm_verifier.select(
        problem=document["problem"],
        candidates=[candidate["trajectory"] for candidate in candidates],
        criteria=document["criteria"],
        n_evaluations=parameters["n_evaluations"],
        pivots=parameters["pivots"],
        seed=parameters["seed"],
        max_workers=1 if backend["kind"] == "omp" else None,
        model=backend["model"],
        cache=str(effective_cache),
        progress=False,
        on_error="raise",
        client=client,
    )
    after_usage = llm_verifier.token_usage()
    after_cache = file_digest(effective_cache)
    usage = {
        key: after_usage.get(key, 0) - before_usage.get(key, 0)
        for key in (
            "calls", "input_tokens", "cached_input_tokens",
            "uncached_input_tokens", "output_tokens", "reasoning_tokens",
        )
    }
    if (backend["kind"] == "omp"
            and any(not isinstance(value, (int, float)) or value < 0
                    for value in usage.values())):
        raise OmpBackendError("verifier returned invalid token usage")
    ids = [candidate["id"] for candidate in candidates]
    evidence = {
        "schema_version": EVIDENCE_VERSION,
        "outcome": "delivered",
        "evidence_level": (
            "integration_smoke" if backend["kind"] == "fixture"
            else "model_run"),
        "run_id": document["run_id"],
        "request_sha256": request_sha256,
        "source": {
            "repository": VERIFIER_REPOSITORY,
            "artifact": VERIFIER_ARTIFACT,
            "artifact_sha256": VERIFIER_ARTIFACT_SHA256,
            "package_version": getattr(llm_verifier, "__version__", "unknown"),
        },
        "backend": backend,
        "parameters": parameters,
        "candidates": [
            {"id": candidate["id"],
             "trajectory_sha256": digest(candidate["trajectory"].encode("utf-8"))}
            for candidate in candidates
        ],
        "criteria_sha256": digest(document["criteria"]),
        "cache_status": (
            "cached" if before_cache is not None and before_cache == after_cache
            else "fresh"),
        "ranking": [ids[index] for index in result.ranking],
        "scores": {ids[index]: result.scores[index]
                   for index in range(len(ids))},
        "n_comparisons": result.n_comparisons,
        "criteria": result.criteria,
        "usage": usage,
        "limitations": ([
            "deterministic fixture backend; model quality is not evaluated",
        ] if backend["kind"] == "fixture" else ([
            "OMP returns literal score tokens; logprob distributions are unavailable",
        ] if backend["kind"] == "omp" else [])),
    }
    if backend["kind"] == "omp":
        evidence["adapter"] = {
            "protocol": OMP_RESULT_VERSION,
            "transport": "explicit_extension_command",
            "model_fallback": "disabled",
        }
        evidence["scoring"] = {
            "mode": "literal",
            "logprob_distribution": False,
        }
        evidence["serving_models"] = sorted(client.models.serving_models)
        evidence["usage"]["reported_cost_usd"] = round(
            client.models.reported_cost_usd, 12)
    return evidence


def failure(code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_VERSION,
        "outcome": "failed",
        "error": {"code": code, "message": message},
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--request", required=True, type=Path)
    run_parser.add_argument("--cache", required=True, type=Path)
    run_parser.add_argument("--omp-command", nargs="+", default=["omp"])
    args = parser.parse_args(argv)
    try:
        document = validate_request(json.loads(
            args.request.read_text(encoding="utf-8")))
    except OSError:
        print(json.dumps(failure(
            "INVALID_REQUEST", "request file cannot be read"),
            ensure_ascii=False, sort_keys=True))
        return 2
    except (json.JSONDecodeError, RequestError) as error:
        print(json.dumps(failure("INVALID_REQUEST", str(error)),
                         ensure_ascii=False, sort_keys=True))
        return 2
    try:
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        evidence = run_evaluation(document, args.cache, args.omp_command)
    except ModuleNotFoundError as error:
        module = error.name or "unknown"
        print(json.dumps(failure(
            "DEPENDENCY_UNAVAILABLE",
            f"required module {module!r} is unavailable"),
            ensure_ascii=False, sort_keys=True))
        return 1
    except Exception as error:
        print(json.dumps(failure("VERIFIER_FAILED", type(error).__name__),
                         ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
