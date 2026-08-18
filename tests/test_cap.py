from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "cap.py"
SPEC = importlib.util.spec_from_file_location("cap_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
cap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cap)


class NonTTY(io.StringIO):
    def isatty(self) -> bool:
        return False


class CapEntryTest(unittest.TestCase):
    def test_bare_entry_selects_profile_cli_args_and_launches(self) -> None:
        args = cap._build_parser().parse_args([])
        with (
            patch.object(cap, "_available_profiles", return_value=["assembly-helper", "general"]),
            patch.object(cap, "_choose", side_effect=["general", "omp"]) as choose,
            patch("builtins.input", return_value="--version"),
            patch.object(cap, "_run_selected", return_value=17) as run_selected,
        ):
            result = cap._interactive_use(args, {})

        self.assertEqual(result, 17)
        self.assertEqual([call.args[0] for call in choose.call_args_list], ["profile", "CLI"])
        self.assertEqual(args.profile, "general")
        self.assertEqual(args.cli, "omp")
        self.assertEqual(args.client_args, ["--version"])
        self.assertEqual(args.profile_tool_command, "launch")
        run_selected.assert_called_once_with(args, {})

    def test_help_remains_explicit_and_old_aliases_fail(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as help_exit:
                cap.main(["--help"])
        self.assertEqual(help_exit.exception.code, 0)

        for alias in ("i", "interactive"):
            stderr = io.StringIO()
            with self.subTest(alias=alias), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as alias_exit:
                    cap.main([alias])
            self.assertNotEqual(alias_exit.exception.code, 0)
            self.assertIn("请使用裸 cap", stderr.getvalue())

    def test_incomplete_non_tty_calls_fail_without_interaction(self) -> None:
        for argv, expected in (([], "裸 cap"), (["show"], "cap show")):
            stderr = io.StringIO()
            with (
                self.subTest(argv=argv),
                patch.object(cap.sys, "stdin", NonTTY()),
                patch.object(cap.sys, "stdout", NonTTY()),
                patch.object(cap, "_interactive_use") as interactive_use,
                patch.object(cap, "_show") as show,
                contextlib.redirect_stderr(stderr),
            ):
                result = cap.main(argv)
            self.assertEqual(result, 2)
            self.assertIn(expected, stderr.getvalue())
            interactive_use.assert_not_called()
            show.assert_not_called()

    def test_explicit_run_and_render_remain_non_interactive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            common = [
                "--project",
                str(root),
                "--home",
                str(root / "home"),
                "--agent-home-root",
                str(root / "agent-homes"),
                "--profile-tool",
                str(root / "caprun.py"),
            ]
            cases = (
                ([*common, "run", "general", "--cli", "omp", "--", "-p", "check"], "run"),
                ([*common, "render", "general", "--cli", "omp", "--output", str(root / "rendered")], "materialize"),
            )
            for argv, command in cases:
                with (
                    self.subTest(command=command),
                    patch.object(cap.sys, "stdin", NonTTY()),
                    patch.object(cap.sys, "stdout", NonTTY()),
                    patch.object(cap, "_run_selected", return_value=23) as run_selected,
                ):
                    result = cap.main(argv)
                self.assertEqual(result, 23)
                selected = run_selected.call_args.args[0]
                self.assertEqual(selected.profile_tool_command, command)


class CapShowTest(unittest.TestCase):
    def test_explicit_profile_outputs_public_closure_without_prompt(self) -> None:
        args = cap._build_parser().parse_args(["show", "general"])
        explanation = {"profile": "general", "inventory": {"skills": []}, "clients": {}}
        stdout = io.StringIO()
        with (
            patch.object(cap, "_profile_json", return_value=explanation),
            patch.object(cap, "_choose") as choose,
            patch.object(cap, "_render_preview") as render_preview,
            contextlib.redirect_stdout(stdout),
        ):
            result = cap._show(args, {})

        self.assertEqual(result, 0)
        self.assertEqual(json_from(stdout), explanation)
        choose.assert_not_called()
        render_preview.assert_not_called()

    def test_interactive_show_outputs_public_closure_then_allows_no_expansion(self) -> None:
        args = cap._build_parser().parse_args(["show"])
        explanation = {"profile": "general", "inventory": {"skills": []}, "clients": {}}
        stdout = io.StringIO()
        with (
            patch.object(cap, "_available_profiles", return_value=["assembly-helper", "general"]),
            patch.object(cap, "_choose", side_effect=["general", "不展开"]) as choose,
            patch.object(cap, "_profile_json", return_value=explanation),
            patch.object(cap, "_render_preview") as render_preview,
            contextlib.redirect_stdout(stdout),
        ):
            result = cap._show(args, {})

        self.assertEqual(result, 0)
        self.assertEqual([call.args[0] for call in choose.call_args_list], ["profile", "CLI 装配"])
        self.assertEqual(json_from(stdout), explanation)
        render_preview.assert_not_called()

    def test_explicit_cli_combines_public_closure_and_preview(self) -> None:
        args = cap._build_parser().parse_args(["show", "general", "--cli", "omp"])
        explanation = {"profile": "general", "inventory": {"skills": []}, "clients": {}}
        preview = {"client": "omp", "files": ["config.yml"], "tree_hash": "sha256:test"}
        stdout = io.StringIO()
        with (
            patch.object(cap, "_profile_json", return_value=explanation),
            patch.object(cap, "_render_preview", return_value=preview),
            patch.object(cap, "_choose") as choose,
            contextlib.redirect_stdout(stdout),
        ):
            result = cap._show(args, {})

        self.assertEqual(result, 0)
        self.assertEqual(json_from(stdout)["preview"], preview)
        choose.assert_not_called()


class CapPreviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.args = cap._build_parser().parse_args(["show", "general", "--cli", "omp"])
        self.real_temporary_directory = tempfile.TemporaryDirectory

    def test_preview_lists_sorted_relative_files_and_cleans_success(self) -> None:
        created: list[str] = []

        def tracked_directory(*args: object, **kwargs: object) -> tempfile.TemporaryDirectory[str]:
            directory = self.real_temporary_directory(*args, **kwargs)
            created.append(directory.name)
            return directory

        def render(preview_args: object, _env: object, _stage: object) -> dict[str, object]:
            output = Path(preview_args.output)
            (output / "skills" / "sample").mkdir(parents=True)
            (output / "skills" / "sample" / "SKILL.md").write_text("skill\n", encoding="utf-8")
            (output / "config.yml").write_text("config\n", encoding="utf-8")
            return {"tree_hash": "sha256:test"}

        with (
            patch.object(cap.tempfile, "TemporaryDirectory", side_effect=tracked_directory),
            patch.object(cap, "_profile_json", side_effect=render),
        ):
            preview = cap._render_preview(self.args, {})

        self.assertEqual(
            preview,
            {
                "client": "omp",
                "files": ["config.yml", "skills/sample/SKILL.md"],
                "tree_hash": "sha256:test",
            },
        )
        self.assertTrue(created)
        self.assertTrue(all(not os.path.exists(path) for path in created))

    def test_preview_cleans_render_failure(self) -> None:
        created: list[str] = []

        def tracked_directory(*args: object, **kwargs: object) -> tempfile.TemporaryDirectory[str]:
            directory = self.real_temporary_directory(*args, **kwargs)
            created.append(directory.name)
            return directory

        with (
            patch.object(cap.tempfile, "TemporaryDirectory", side_effect=tracked_directory),
            patch.object(cap, "_profile_json", return_value=None),
        ):
            preview = cap._render_preview(self.args, {})

        self.assertIsNone(preview)
        self.assertTrue(created)
        self.assertTrue(all(not os.path.exists(path) for path in created))


def json_from(buffer: io.StringIO) -> dict[str, object]:
    import json

    payload = json.loads(buffer.getvalue())
    assert isinstance(payload, dict)
    return payload


if __name__ == "__main__":
    unittest.main()
