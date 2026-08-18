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

    def run_cli(self, document):
        self.request_path.write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(STUB)
        return subprocess.run(
            [sys.executable, str(SCRIPT), "run", "--request",
             str(self.request_path), "--cache", str(self.cache_path)],
            cwd=ROOT, env=env, text=True, capture_output=True,
            encoding="utf-8", check=False,
        )

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


if __name__ == "__main__":
    unittest.main()
