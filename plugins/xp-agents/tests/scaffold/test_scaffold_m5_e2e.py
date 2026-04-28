#!/usr/bin/env python3
"""Milestone-5 capstone E2E for /xp-scaffold-acceptance.

Validates the cross-cutting M-5 done state by composing the helpers
shipped in stories 003-004 against a fixture pnpm monorepo:

  <tmp>/repo/
  ├── pnpm-workspace.yaml
  ├── packages/web/playwright.config.ts  (committed at HEAD-1)
  └── packages/api/                      (gap surface)

Two tests exercise the cross-cutting flow:

1. find-introducing-commit pin-points the commit that introduced
   packages/web/playwright.config.ts (the redo pointer Step 1c surfaces).
2. detect-monorepo lists both packages AND the apply pipeline, when
   driven against packages/api with --repo-root scoped to that package,
   lands a covered surface flip — proving the Step 1d path-placement
   choice flows through Steps 4-9 unchanged.

The unit-level HEAD-advancement gate is already covered by
test_scaffold_record.TestRecordScaffoldHeadAdvancementGate; this
capstone focuses on the monorepo-routing delta.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _helpers import init_git_identity, run_git, valid_system_context
from conftest import run_cli

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"


def _setup_monorepo(repo: Path) -> str:
    """Build the pnpm-monorepo fixture; return the introducing-commit sha.

    Layout:
      pnpm-workspace.yaml          (packages: ["packages/*"])
      packages/web/playwright.config.ts  ← HEAD-1
      packages/api/.gitkeep         ← HEAD
    """
    init_git_identity(repo)
    (repo / "pnpm-workspace.yaml").write_text(
        'packages:\n  - "packages/*"\n', encoding="utf-8"
    )
    (repo / "packages" / "web").mkdir(parents=True)
    (repo / "packages" / "api").mkdir(parents=True)
    (repo / "packages" / "api" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(["git", "add", "."], repo)
    run_git(["git", "commit", "-m", "init monorepo"], repo)

    (repo / "packages" / "web" / "playwright.config.ts").write_text(
        "export default {};\n", encoding="utf-8"
    )
    run_git(["git", "add", "packages/web/playwright.config.ts"], repo)
    run_git(["git", "commit", "-m", "add playwright to packages/web"], repo)
    return run_git(["git", "rev-parse", "HEAD"], repo).stdout.strip()


def _setup_smm(smm_dir: Path) -> None:
    """SMM with a 'browser' gap surface for packages/api scaffolding."""
    ctx = valid_system_context(
        surfaces=[
            {
                "name": "browser",
                "signals": ["next.js"],
                "harness": "playwright",
                "status": "gap",
            }
        ]
    )
    ctx["branching_strategy"] = {"stage": 0}
    (smm_dir / "system_context.json").write_text(json.dumps(ctx), encoding="utf-8")


_PLAN_INPUT = {
    "surface": "browser",
    "tool": "playwright",
    "tool_version": "1.51.0",
    "files_to_create": [
        {
            "path": "tests/acceptance/example.spec.ts",
            "description": "happy",
            "body": "export default 1;\n",
        }
    ],
    "files_to_modify": [],
    "install_cmds": ["true"],
    "verify_cmd": "true",
    "branch_name": "paul/scaffold-browser-acceptance",
}


class TestScaffoldM5Capstone(unittest.TestCase):
    """Pins the M-5 done state: re-invocation pointer + monorepo path routing."""

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="scaffold-m5-repo-"))
        self.smm_dir = Path(tempfile.mkdtemp(prefix="scaffold-m5-smm-"))
        self.intro_sha = _setup_monorepo(self.repo)
        _setup_smm(self.smm_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.smm_dir, ignore_errors=True)

    def _run(self, argv: list[str], stdin_data: str = "") -> dict:
        result = run_cli(_CLI, argv, self.smm_dir, stdin_data=stdin_data)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_redo_pointer_for_packages_web(self) -> None:
        """find-introducing-commit returns the playwright-add commit when
        given packages/web/playwright.config.ts. Step 1c redo branch reads
        this output to print the revert pointer."""
        cfg = self.repo / "packages" / "web" / "playwright.config.ts"
        result = run_cli(
            _CLI,
            [
                "find-introducing-commit",
                "--repo-root",
                str(self.repo),
                "--config-files",
                str(cfg),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sha"], self.intro_sha)
        self.assertEqual(payload["subject"], "add playwright to packages/web")

    def test_monorepo_path_routes_apply_against_subpackage(self) -> None:
        """detect-monorepo lists both packages, AND the apply pipeline runs
        cleanly when --repo-root is scoped to packages/api (the gap),
        flipping the surface covered. Validates that Step 1d's path
        choice flows through Steps 4-9 unchanged.
        """
        mono = json.loads(
            run_cli(
                _CLI,
                ["detect-monorepo", "--repo-root", str(self.repo)],
                self.smm_dir,
            ).stdout
        )
        self.assertTrue(mono["is_monorepo"])
        self.assertEqual(mono["kind"], "pnpm")
        self.assertIn("packages/web", mono["packages"])
        self.assertIn("packages/api", mono["packages"])

        api_root = self.repo / "packages" / "api"

        write_payload = self._run(
            ["apply-write", "--repo-root", str(api_root)],
            stdin_data=json.dumps(_PLAN_INPUT),
        )
        snap_id = write_payload["snapshot_id"]
        self.addCleanup(shutil.rmtree, write_payload["snapshot_dir"], True)

        self._run(
            ["apply-install", "--snapshot-id", snap_id, "--repo-root", str(api_root)]
        )
        self._run(
            ["apply-verify", "--snapshot-id", snap_id, "--repo-root", str(api_root)]
        )
        commit_payload = self._run(
            [
                "apply-commit",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                str(api_root),
                "--surface",
                "browser",
                "--tool",
                "playwright",
                "--concern-id",
                "abc123def456",
            ]
        )
        self.assertTrue(commit_payload["ok"])

        self._run(
            [
                "apply-record",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                str(api_root),
                "--surface",
                "browser",
                "--concern-id",
                "abc123def456",
                "--agent-id",
                "test-agent",
                "--commit-sha",
                commit_payload["sha"],
            ]
        )

        # The scaffold's test file landed under packages/api/, not the repo root.
        scaffolded = api_root / "tests" / "acceptance" / "example.spec.ts"
        self.assertTrue(scaffolded.exists(), f"expected scaffold under {api_root}")
        self.assertFalse(
            (self.repo / "tests" / "acceptance" / "example.spec.ts").exists(),
            "scaffold leaked outside packages/api — Step 1d routing broke",
        )

        # Surface flipped covered + template stamped.
        ctx = json.loads(
            (self.smm_dir / "system_context.json").read_text(encoding="utf-8")
        )
        browser = next(s for s in ctx["acceptance_surfaces"] if s["name"] == "browser")
        self.assertEqual(browser["status"], "covered")
        self.assertEqual(browser["acceptance_template_command"], "true")


if __name__ == "__main__":
    unittest.main()
