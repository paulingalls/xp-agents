#!/usr/bin/env python3
"""Tests for scaffold_post.build_commit_message — pure subject + trailer formatter."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from scaffold_post import build_commit_message


class TestBuildCommitMessage(unittest.TestCase):
    def _msg(
        self,
        *,
        surface: str = "browser",
        tool: str = "playwright",
        tool_version: str = "1.51.0",
        verify_cmd: str = "npx playwright test tests/acceptance/example.spec.ts",
        files_created: list[str] | None = None,
        files_modified: list[str] | None = None,
        concern_id: str | None = None,
    ) -> str:
        if files_created is None:
            files_created = ["tests/acceptance/example.spec.ts", "playwright.config.ts"]
        if files_modified is None:
            files_modified = [".gitignore", "package.json"]
        return build_commit_message(
            surface=surface,
            tool=tool,
            tool_version=tool_version,
            verify_cmd=verify_cmd,
            files_created=files_created,
            files_modified=files_modified,
            concern_id=concern_id,
        )

    def test_subject_uses_doctrine_format(self) -> None:
        msg = self._msg()
        first = msg.splitlines()[0]
        self.assertEqual(first, "[chore] Scaffold browser acceptance via playwright")

    def test_subject_substitutes_surface_and_tool(self) -> None:
        msg = self._msg(surface="api", tool="pytest")
        first = msg.splitlines()[0]
        self.assertEqual(first, "[chore] Scaffold api acceptance via pytest")

    def test_includes_tool_version_trailer(self) -> None:
        msg = self._msg(tool_version="2.0.0-beta.1")
        self.assertIn("Tool-version: 2.0.0-beta.1", msg)

    def test_includes_files_created_trailer(self) -> None:
        msg = self._msg(files_created=["a.ts", "b/c.ts"])
        self.assertIn("Files-created: a.ts, b/c.ts", msg)

    def test_includes_files_modified_trailer(self) -> None:
        msg = self._msg(files_modified=[".gitignore", "package.json"])
        self.assertIn("Files-modified: .gitignore, package.json", msg)

    def test_omits_files_created_when_empty(self) -> None:
        msg = self._msg(files_created=[])
        self.assertNotIn("Files-created:", msg)

    def test_omits_files_modified_when_empty(self) -> None:
        msg = self._msg(files_modified=[])
        self.assertNotIn("Files-modified:", msg)

    def test_includes_verification_trailer(self) -> None:
        msg = self._msg(verify_cmd="pytest tests/acceptance")
        self.assertIn("Verification: pytest tests/acceptance", msg)

    def test_resolves_event_trailer_with_concern_id(self) -> None:
        msg = self._msg(concern_id="abc123def456")
        lines = msg.splitlines()
        self.assertIn("Resolves-Event: abc123def456", lines)

    def test_resolves_event_trailer_none_when_concern_omitted(self) -> None:
        msg = self._msg(concern_id=None)
        lines = msg.splitlines()
        self.assertIn("Resolves-Event: none", lines)

    def test_resolves_event_is_last_trailer(self) -> None:
        """Resolves-Event is the canonical last trailer per doctrine."""
        msg = self._msg(concern_id="abc123def456")
        non_empty = [line for line in msg.splitlines() if line.strip()]
        self.assertEqual(non_empty[-1], "Resolves-Event: abc123def456")

    def test_subject_separated_from_trailers_by_blank_line(self) -> None:
        """git interpret-trailers needs a blank line between subject and trailers."""
        msg = self._msg()
        lines = msg.split("\n")
        self.assertTrue(lines[0].startswith("[chore] Scaffold"))
        self.assertEqual(lines[1], "")
        self.assertTrue(lines[2].startswith("Tool-version:"))


if __name__ == "__main__":
    unittest.main()
