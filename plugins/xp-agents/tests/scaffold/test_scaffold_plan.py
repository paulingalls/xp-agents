#!/usr/bin/env python3
"""Tests for scaffold_plan.py — pure-logic plan/preview/decline helpers."""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from scaffold_plan import (
    COMMIT_MSG_TEMPLATE,
    PROCEED_PROMPT,
    DeclineResult,
    ScaffoldPlan,
    build_plan,
    decline_if_unreliable,
    render_preview,
)


def _sample_plan(**overrides) -> ScaffoldPlan:
    args = dict(
        surface="browser",
        tool="playwright",
        tool_version="1.51.0",
        files_to_create=[
            {
                "path": "tests/acceptance/example.spec.ts",
                "description": "happy-path test",
                "line_count": 12,
            },
            {
                "path": "playwright.config.ts",
                "description": "single-project browser config",
                "line_count": 18,
            },
        ],
        files_to_modify=[
            {"path": ".gitignore", "description": "+1 line for playwright artifacts"},
            {
                "path": "package.json",
                "description": "+@playwright/test devDep, +scripts.test:acceptance",
            },
        ],
        install_cmds=["npm install", "npx playwright install chromium"],
        verify_cmd="npx playwright test tests/acceptance/example.spec.ts",
        branch_name="paul/scaffold-browser-acceptance",
    )
    args.update(overrides)
    return build_plan(**args)


class TestBuildPlan(unittest.TestCase):
    def test_returns_scaffold_plan_dataclass(self) -> None:
        plan = _sample_plan()
        self.assertIsInstance(plan, ScaffoldPlan)

    def test_commit_msg_uses_template(self) -> None:
        plan = _sample_plan()
        expected = COMMIT_MSG_TEMPLATE.format(
            surface="browser", tool="playwright", tool_version="1.51.0"
        )
        self.assertEqual(plan.commit_msg, expected)

    def test_files_to_create_entries_have_path_and_description(self) -> None:
        plan = _sample_plan()
        for entry in plan.files_to_create:
            self.assertIn("path", entry)
            self.assertIn("description", entry)

    def test_surface_and_tool_round_trip(self) -> None:
        plan = _sample_plan()
        self.assertEqual(plan.surface, "browser")
        self.assertEqual(plan.tool, "playwright")
        self.assertEqual(plan.tool_version, "1.51.0")

    def test_defensive_copies_lists(self) -> None:
        files_to_create = [{"path": "a.ts", "description": "a"}]
        plan = build_plan(
            surface="browser",
            tool="playwright",
            tool_version="1.0",
            files_to_create=files_to_create,
            files_to_modify=[],
            install_cmds=[],
            verify_cmd="echo ok",
            branch_name="x",
        )
        files_to_create.append({"path": "b.ts", "description": "b"})
        self.assertEqual(len(plan.files_to_create), 1)


class TestRenderPreview(unittest.TestCase):
    def setUp(self) -> None:
        self.preview = render_preview(_sample_plan())

    def test_contains_doctrine_sections(self) -> None:
        for marker in (
            "Selected surface",
            "Selected tool",
            "Planning scaffold",
            "Install + verify",
            "Commit plan",
        ):
            self.assertIn(marker, self.preview, f"preview missing section: {marker}")

    def test_lists_files_to_create_paths(self) -> None:
        self.assertIn("tests/acceptance/example.spec.ts", self.preview)
        self.assertIn("playwright.config.ts", self.preview)

    def test_lists_files_to_modify_paths(self) -> None:
        self.assertIn(".gitignore", self.preview)
        self.assertIn("package.json", self.preview)

    def test_lists_install_and_verify_commands(self) -> None:
        self.assertIn("npm install", self.preview)
        self.assertIn("npx playwright test", self.preview)

    def test_includes_branch_name(self) -> None:
        self.assertIn("paul/scaffold-browser-acceptance", self.preview)

    def test_ends_with_proceed_prompt(self) -> None:
        self.assertTrue(
            self.preview.rstrip().endswith(PROCEED_PROMPT),
            f"preview must end with the verbatim proceed prompt; got tail: "
            f"{self.preview.rstrip()[-80:]!r}",
        )


class TestRenderPreviewEdgeCases(unittest.TestCase):
    def test_empty_file_lists_render_cleanly(self) -> None:
        plan = _sample_plan(files_to_create=[], files_to_modify=[])
        preview = render_preview(plan)
        self.assertIn("Planning scaffold", preview)
        self.assertNotIn("  Create:", preview)
        self.assertNotIn("  Modify:", preview)
        self.assertTrue(preview.rstrip().endswith(PROCEED_PROMPT))

    def test_missing_line_count_omits_lines_suffix(self) -> None:
        plan = _sample_plan(
            files_to_create=[{"path": "x.ts", "description": "no count"}]
        )
        preview = render_preview(plan)
        self.assertIn("Create: x.ts (no count)", preview)
        self.assertNotIn("None lines", preview)

    def test_files_to_modify_ignores_line_count(self) -> None:
        plan = _sample_plan(
            files_to_modify=[
                {"path": "y.json", "description": "+1 dep", "line_count": 999}
            ]
        )
        preview = render_preview(plan)
        self.assertIn("Modify: y.json (+1 dep)", preview)
        self.assertNotIn("999", preview)

    def test_special_chars_in_tool_pass_through_commit_msg(self) -> None:
        plan = _sample_plan(tool="@scope/runner", tool_version="2.0.0-beta.1")
        self.assertIn("@scope/runner", plan.commit_msg)
        self.assertIn("2.0.0-beta.1", plan.commit_msg)


class TestDeclineIfUnreliable(unittest.TestCase):
    def test_returns_decline_result_named_tuple(self) -> None:
        result = decline_if_unreliable("custom-tool", None)
        self.assertIsInstance(result, DeclineResult)

    def test_declines_on_none(self) -> None:
        result = decline_if_unreliable("custom-tool", None)
        self.assertTrue(result.decline)
        self.assertIsNotNone(result.reason)

    def test_declines_on_empty_string(self) -> None:
        result = decline_if_unreliable("custom-tool", "")
        self.assertTrue(result.decline)
        self.assertIsNotNone(result.reason)

    def test_declines_on_whitespace_only(self) -> None:
        result = decline_if_unreliable("custom-tool", "   \n  ")
        self.assertTrue(result.decline)

    def test_passes_through_with_guidance(self) -> None:
        result = decline_if_unreliable(
            "custom-tool",
            "Install via npm install custom-tool@latest; configure custom.config.js",
        )
        self.assertFalse(result.decline)
        self.assertIsNone(result.reason)

    def test_reason_mentions_tool_name(self) -> None:
        result = decline_if_unreliable("obscure-runner", None)
        self.assertIn("obscure-runner", result.reason)


class TestModuleHygiene(unittest.TestCase):
    """Stdlib-only / no-side-effects sanity checks via AST inspection."""

    @classmethod
    def setUpClass(cls) -> None:
        path = Path(__file__).parent.parent.parent / "scripts" / "scaffold_plan.py"
        cls.source = path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_no_subprocess_or_network_imports(self) -> None:
        forbidden = {"subprocess", "socket", "urllib", "httpx", "requests"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split(".")[0]
                    self.assertNotIn(
                        head,
                        forbidden,
                        f"forbidden import {alias.name!r} at line {node.lineno}",
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                head = node.module.split(".")[0]
                self.assertNotIn(
                    head,
                    forbidden,
                    f"forbidden from-import {node.module!r} at line {node.lineno}",
                )

    def test_no_top_level_side_effects(self) -> None:
        allowed = (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Import,
            ast.ImportFrom,
            ast.Assign,
            ast.AnnAssign,
            ast.Expr,
        )
        for node in self.tree.body:
            self.assertIsInstance(
                node,
                allowed,
                f"unexpected top-level node at line {node.lineno}",
            )
            if isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant)


if __name__ == "__main__":
    unittest.main()
