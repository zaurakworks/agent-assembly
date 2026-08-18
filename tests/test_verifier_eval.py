import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verifier_eval.py"
STUB = ROOT / "tests" / "fixtures" / "llm_verifier_stub"


def request(candidate_suffix=""):
    return {
        "schema_version": "agent-assembly.verifier-request/v1",
        "run_id": "bootstrap-evidence-fixture",
        "problem": "Judge whether the deployment evidence is sufficient.",
        "candidates": [
            {"id": "pass", "trajectory": "EXPECTED_PASS complete evidence" + candidate_suffix},
            {"id": "reject", "trajectory": "EXPECTED_REJECT fabricated evidence"},
            {"id": "unknown", "trajectory": "EXPECTED_UNKNOWN missing evidence"},
        ],
        "criteria": [{
            "id": "evidence_quality",
            "name": "Evidence quality",
            "description": "Prefer complete, directly reproducible evidence.",
        }],
        "backend": {"kind": "fixture", "model": "fixture-verifier-v1"},
        "parameters": {"n_evaluations": 2, "pivots": 1, "seed": 0},
    }


class VerifierEvaluationCLITest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.request_path = self.root / "request.json"
        self.cache_path = self.root / "cache.json"

    def run_cli(self, document, *, extra_args=None, extra_env=None):
        self.request_path.write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(STUB)
        env.update(extra_env or {})
        command = [
            sys.executable, str(SCRIPT), "run", "--request",
            str(self.request_path), "--cache", str(self.cache_path),
        ]
        command.extend(extra_args or [])
        return subprocess.run(
            command,
            cwd=ROOT, env=env, text=True, capture_output=True,
            encoding="utf-8", check=False,
        )

    def make_fake_omp(self):
        script = self.root / "fake_omp.py"
        script.write_text(
            """import json
import os
import sys

if os.environ.get("FAKE_OMP_MODE") == "command-failure":
    raise SystemExit(7)

command = sys.argv[-1]
prefix = "/agent-assembly-verifier "
if not command.startswith(prefix):
    raise SystemExit(8)
request_path = command[len(prefix):]
with open(request_path, encoding="utf-8") as request_file:
    request = json.load(request_file)

prompt = request["prompt"]
def score(marker):
    if "EXPECTED_PASS" in marker:
        return "A"
    if "EXPECTED_REJECT" in marker:
        return "T"
    return "K"

trace_a = prompt.split("**Trajectory A:**\\n", 1)[1].split(
    "\\n\\n**Trajectory B:**", 1)[0]
trace_b = prompt.split("**Trajectory B:**\\n", 1)[1].split(
    "\\n\\n**Rating Scale:**", 1)[0]
text = f"<score_A> {score(trace_a)} </score_A>\\n<score_B> {score(trace_b)} </score_B>"
if os.environ.get("FAKE_OMP_MODE") == "invalid-score":
    text = "not a score"
actual_model = os.environ.get("FAKE_OMP_MODEL", request["model"])
result = {
    "schema_version": "agent-assembly.omp-completion/v1",
    "requested_model": request["model"],
    "model": actual_model,
    "stop_reason": "length" if os.environ.get("FAKE_OMP_MODE") == "non-stop" else "stop",
    "usage": {
        "input": 19,
        "output": 6,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": 25,
        "cost": {"total": 0.00000434},
    },
    "text": text,
}
print("Working...")
if os.environ.get("FAKE_OMP_MODE") == "fallback":
    print('{"type":"retry_fallback_applied"}')
print("__AGENT_ASSEMBLY_OMP_RESULT__" + json.dumps(result, separators=(",", ":")))
""",
            encoding="utf-8",
        )
        return script

    def test_receipt_reports_fresh_cached_and_changed_inputs_without_content(self):
        first = self.run_cli(request())
        self.assertEqual(first.returncode, 0, first.stderr)
        first_receipt = json.loads(first.stdout)
        self.assertEqual(first_receipt["schema_version"],
                         "agent-assembly.verifier-evidence/v1")
        self.assertEqual(first_receipt["outcome"], "delivered")
        self.assertEqual(first_receipt["cache_status"], "fresh")
        self.assertEqual(first_receipt["ranking"][0], "pass")
        self.assertNotIn("EXPECTED_PASS", first.stdout)
        self.assertNotIn(str(self.root), first.stdout)

        second = self.run_cli(request())
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["cache_status"], "cached")

        changed = self.run_cli(request(" changed"))
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertEqual(json.loads(changed.stdout)["cache_status"], "fresh")

    def test_single_candidate_is_rejected_instead_of_reporting_full_score(self):
        document = request()
        document["candidates"] = document["candidates"][:1]
        result = self.run_cli(document)
        self.assertEqual(result.returncode, 2)
        failure = json.loads(result.stdout)
        self.assertEqual(failure["outcome"], "failed")
        self.assertEqual(failure["error"]["code"], "INVALID_REQUEST")

    def test_missing_runtime_dependency_has_an_actionable_failure_code(self):
        document = request()
        document["backend"]["model"] = "missing-dependency"
        result = self.run_cli(document)
        self.assertEqual(result.returncode, 1)
        failure = json.loads(result.stdout)
        self.assertEqual(failure["error"]["code"],
                         "DEPENDENCY_UNAVAILABLE")
        self.assertIn("google.genai", failure["error"]["message"])

    def test_missing_request_does_not_disclose_the_local_path(self):
        missing = self.root / "private" / "missing-request.json"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(STUB)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "run", "--request", str(missing),
             "--cache", str(self.cache_path)],
            cwd=ROOT, env=env, text=True, capture_output=True,
            encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 2)
        failure = json.loads(result.stdout)
        self.assertEqual(failure["error"]["code"], "INVALID_REQUEST")
        message = failure["error"]["message"].replace("\\\\", "\\")
        self.assertNotIn(str(self.root), message)

    def test_omp_backend_uses_literal_scores_and_reports_serving_model(self):
        document = request()
        document["backend"] = {"kind": "omp", "model": "test/model"}
        fake_omp = self.make_fake_omp()

        result = self.run_cli(
            document,
            extra_args=["--omp-command", sys.executable, str(fake_omp)],
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence["backend"], document["backend"])
        self.assertEqual(evidence["scoring"], {
            "mode": "literal",
            "logprob_distribution": False,
        })
        self.assertEqual(evidence["serving_models"], ["test/model"])
        self.assertEqual(evidence["ranking"][0], "pass")
        self.assertTrue(any(
            "OMP returns literal score tokens" in limitation
            for limitation in evidence["limitations"]
        ))
        self.assertNotIn("EXPECTED_PASS", result.stdout)
        self.assertNotIn(str(self.root), result.stdout)

        cached = self.run_cli(
            document,
            extra_args=["--omp-command", sys.executable, str(fake_omp)],
        )
        self.assertEqual(cached.returncode, 0, cached.stderr)
        cached_evidence = json.loads(cached.stdout)
        self.assertEqual(cached_evidence["cache_status"], "cached")
        self.assertEqual(cached_evidence["usage"]["calls"], 0)
        self.assertEqual(cached_evidence["usage"]["reported_cost_usd"], 0.0)
        self.assertEqual(cached_evidence["serving_models"], [])

    def test_omp_backend_fails_closed_on_serving_model_mismatch(self):
        document = request()
        document["backend"] = {"kind": "omp", "model": "test/model"}
        fake_omp = self.make_fake_omp()

        result = self.run_cli(
            document,
            extra_args=["--omp-command", sys.executable, str(fake_omp)],
            extra_env={"FAKE_OMP_MODEL": "other/model"},
        )

        self.assertEqual(result.returncode, 1)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence["error"], {
            "code": "VERIFIER_FAILED",
            "message": "OmpBackendError",
        })
        self.assertNotIn("other/model", result.stdout)

    def test_omp_backend_fails_closed_on_invalid_literal_score(self):
        document = request()
        document["backend"] = {"kind": "omp", "model": "test/model"}
        fake_omp = self.make_fake_omp()

        result = self.run_cli(
            document,
            extra_args=["--omp-command", sys.executable, str(fake_omp)],
            extra_env={"FAKE_OMP_MODE": "invalid-score"},
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], {
            "code": "VERIFIER_FAILED",
            "message": "OmpBackendError",
        })

    def test_omp_backend_fails_closed_on_command_failure(self):
        document = request()
        document["backend"] = {"kind": "omp", "model": "test/model"}
        fake_omp = self.make_fake_omp()

        result = self.run_cli(
            document,
            extra_args=["--omp-command", sys.executable, str(fake_omp)],
            extra_env={"FAKE_OMP_MODE": "command-failure"},
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], {
            "code": "VERIFIER_FAILED",
            "message": "OmpBackendError",
        })

    def test_omp_backend_fails_closed_on_fallback_evidence(self):
        document = request()
        document["backend"] = {"kind": "omp", "model": "test/model"}
        fake_omp = self.make_fake_omp()

        result = self.run_cli(
            document,
            extra_args=["--omp-command", sys.executable, str(fake_omp)],
            extra_env={"FAKE_OMP_MODE": "fallback"},
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], {
            "code": "VERIFIER_FAILED",
            "message": "OmpBackendError",
        })

    def test_omp_backend_fails_closed_on_non_stop_completion(self):
        document = request()
        document["backend"] = {"kind": "omp", "model": "test/model"}
        fake_omp = self.make_fake_omp()

        result = self.run_cli(
            document,
            extra_args=["--omp-command", sys.executable, str(fake_omp)],
            extra_env={"FAKE_OMP_MODE": "non-stop"},
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], {
            "code": "VERIFIER_FAILED",
            "message": "OmpBackendError",
        })


if __name__ == "__main__":
    unittest.main()
