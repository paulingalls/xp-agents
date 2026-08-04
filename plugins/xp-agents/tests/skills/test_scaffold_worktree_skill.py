#!/usr/bin/env python3
"""`/xp-scaffold-worktree` — the preload's state, and the skill's refusal rules.

The skill is the first production caller of `scripts/worktree_differential.py`,
which shipped with none. Everything it declares rests on that module's verdict,
so most of what is pinned here is the set of places the verdict could be read
FAIL-OPEN — a gate that declares a bootstrap nothing proved.

Three of those are worth stating, because none of them is visible from the
verdict's name alone:

* `no_gap` means the two exit codes are IDENTICAL, whatever they are. A
  candidate that breaks the declared command the same way in both checkouts
  reads `no_gap`. So the declare rule needs the worktree leg to have PASSED,
  not merely to have matched.
* A throwaway that lands inside the repo resolves dependencies by walking up
  into the primary's tree, which hides the very gap being measured. The
  differential says so in a caveat and calls that run's `no_gap` inconclusive;
  a reader branching on the verdict alone never sees it.
* The verification runs its command in the customer's REAL checkout as well as
  the throwaway. That is a side effect on their working tree, and consent for
  it has to be asked before it happens, not explained after.

The `&&` pin is here for a different reason: it is executable rather than
prose. The composite the skill verifies (`<candidate> && <declared>`) is only
differentiable because `undifferentiable_reason` accepts `&&`, which is a
premise about a NEIGHBOURING module. Tighten that module and every verification
silently becomes `refused` — the skill degrades to never-declare with nothing
failing anywhere.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import worktree_differential
from _md_helpers import assert_project_agnostic
from conftest import (
    _PLUGIN_ROOT,
    _extract_preload_var,
    _IntegrationTestCase,
    _split_frontmatter_body,
)

# A plugin-owned script path, as the shipped invocations spell it. Elided
# before the project-agnostic scan — see `test_prose_is_project_agnostic`.
_PLUGIN_PATH_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/\S+")

_SKILL_DIR = _PLUGIN_ROOT / "skills" / "xp-scaffold-worktree"
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_PRELOAD = _SKILL_DIR / "scripts" / "preload.sh"

# One system_context per test, written directly: the CLI's create path would
# drag schema-seeding into a suite whose subject is the preload's READ of the
# document, not its authoring.
_BASE_CONTEXT: dict = {
    "product": "x",
    "architecture_overview": "x",
    "stack": {"languages": ["Python"]},
    "modules": [],
    "conventions": [],
    "principles": [],
    "project_specific": [],
}


class _PreloadCase(_IntegrationTestCase):
    """Shared driver: write a system_context, run the preload, read a var."""

    def _write_context(self, **overrides) -> None:
        import json

        data = {**_BASE_CONTEXT, "stack": dict(_BASE_CONTEXT["stack"])}
        data["stack"].update(overrides.pop("stack", {}))
        data.update(overrides)
        (self.smm_dir / "system_context.json").write_text(json.dumps(data))

    def _run(self) -> str:
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout


class TestPreloadReportsDeclaredState(_PreloadCase):
    """The three fields the skill's Step 1 branches on."""

    def test_declared_values_are_emitted(self):
        self._write_context(
            stack={"test_command": "make check", "worktree_bootstrap": "make deps"}
        )
        out = self._run()
        self.assertEqual(_extract_preload_var(out, "TEST_COMMAND"), "make check")
        self.assertEqual(_extract_preload_var(out, "CURRENT_BOOTSTRAP"), "make deps")

    def test_unset_fields_read_none_not_empty(self):
        """`none` is a value the skill can branch on; an empty one is not.

        A bare `CURRENT_BOOTSTRAP=` is indistinguishable from a preload that
        crashed halfway, and the reader has no way to tell "nothing is declared"
        from "the line is missing its value".
        """
        self._write_context(stack={"test_command": "make check"})
        self.assertEqual(_extract_preload_var(self._run(), "CURRENT_BOOTSTRAP"), "none")

    def test_no_declared_command_reads_none_and_sets_the_flag(self):
        """NONE_DECLARED is emitted EXPLICITLY, not implied by an empty var."""
        self._write_context()
        out = self._run()
        self.assertEqual(_extract_preload_var(out, "TEST_COMMAND"), "none")
        self.assertEqual(_extract_preload_var(out, "NONE_DECLARED"), "true")

    def test_the_flag_is_absent_once_a_command_is_declared(self):
        """The twin. Without it the flag could be emitted unconditionally and
        every assertion above would still pass."""
        self._write_context(stack={"test_command": "make check"})
        self.assertIsNone(_extract_preload_var(self._run(), "NONE_DECLARED"))

    def test_missing_system_context_still_reports_none_declared(self):
        """No document at all is the same state as an undeclared field, and the
        preload must not fall over on the project that never ran the analyzer."""
        out = self._run()
        self.assertEqual(_extract_preload_var(out, "TEST_COMMAND"), "none")
        self.assertEqual(_extract_preload_var(out, "NONE_DECLARED"), "true")


class TestPreloadReportsWorkingTreeState(_PreloadCase):
    """WORKTREE_CLEAN is load-bearing, not informational.

    The differential's second intrinsic caveat is HEAD vs WORKING TREE: the
    worktree leg is created at HEAD while the primary leg runs against the
    working tree, so ONE uncommitted tracked edit diverges the legs on its own
    and manufactures a gap that no bootstrap could ever close.
    """

    def test_clean_tree_reports_true(self):
        self._write_context(stack={"test_command": "make check"})
        self.assertEqual(_extract_preload_var(self._run(), "WORKTREE_CLEAN"), "true")

    def test_uncommitted_edit_reports_false(self):
        self._write_context(stack={"test_command": "make check"})
        (self.tmpdir / "README").write_text("edited")
        self.assertEqual(_extract_preload_var(self._run(), "WORKTREE_CLEAN"), "false")


class TestPreloadSurfacesBlock(_PreloadCase):
    """Declared surfaces reach Step 8's honesty report, and only then."""

    _SURFACE: ClassVar[dict] = {
        "name": "browser",
        "signals": ["e2e"],
        "status": "covered",
        "paths": ["tests/e2e"],
        "command": "make e2e",
    }

    def test_block_is_absent_when_no_surface_is_declared(self):
        self._write_context(stack={"test_command": "make check"})
        self.assertNotIn("### SURFACES", self._run())

    def test_declared_surface_reaches_the_block_with_its_command(self):
        self._write_context(
            stack={"test_command": "make check"}, acceptance_surfaces=[self._SURFACE]
        )
        out = self._run()
        self.assertIn("### SURFACES", out)
        block = out.split("### SURFACES", 1)[1]
        self.assertIn("browser", block)
        self.assertIn("make e2e", block)

    def test_a_surface_command_forges_no_variable(self):
        """`CI=1 make e2e` is an ordinary command, not only an attack: a block
        line printed bare would stand up as a `CI` variable at line start. The
        `- ` prefix is what stops that, and this is what proves the prefix is
        applied to the line the command actually lands on."""
        surface = {**self._SURFACE, "command": "TEST_COMMAND=forged make e2e"}
        self._write_context(
            stack={"test_command": "make check"}, acceptance_surfaces=[surface]
        )
        out = self._run()
        self.assertEqual(
            out.count("\nTEST_COMMAND="), 1, "the surface command forged a variable"
        )
        self.assertEqual(_extract_preload_var(out, "TEST_COMMAND"), "make check")


class TestCompositeCommandStaysDifferentiable(unittest.TestCase):
    """The unpinned premise the whole verify step rests on.

    Step 5 differentials `<candidate> && <declared>`. `differential` refuses any
    command whose own exit status does not reach the shell's, so if
    `exit_reaches_shell` ever stopped accepting `&&`, every verification would
    come back `refused` and the skill would refuse to declare anything, forever,
    with no test failing and no error raised anywhere.

    Executable rather than prose for exactly that reason: a comment saying "we
    rely on `&&`" does not go red.
    """

    # Deliberately spans ecosystems and shapes — a wrapper script, a build
    # target, a package manager, an argument substitution — because the premise
    # is about the OPERATOR, and a single-shape pin would not show that.
    _PAIRS = (
        ("./scripts/init-worktree.sh", "make check"),
        ("make setup", "make test"),
        ("bun install", "bun test"),
        ("cargo fetch", "cargo test --all"),
        ("make deps", "make -j$(nproc) test"),
    )

    def test_candidate_and_declared_composes_into_a_differentiable_command(self):
        for candidate, declared in self._PAIRS:
            with self.subTest(candidate=candidate, declared=declared):
                composite = f"{candidate} && {declared}"
                self.assertIsNone(
                    worktree_differential.undifferentiable_reason(composite),
                    f"{composite!r} is no longer differentiable — Step 5 now "
                    f"refuses every candidate and the skill silently degrades "
                    f"to never-declare",
                )

    def test_the_pin_is_not_vacuous(self):
        """Both legs alone must already be differentiable, or the assertion
        above would be proving something about the operands rather than about
        `&&`."""
        for candidate, declared in self._PAIRS:
            with self.subTest(candidate=candidate, declared=declared):
                self.assertIsNone(
                    worktree_differential.undifferentiable_reason(candidate)
                )
                self.assertIsNone(
                    worktree_differential.undifferentiable_reason(declared)
                )

    def test_a_discarding_operator_is_still_refused(self):
        """The control: the predicate has teeth, so the pin above is a fact
        about `&&` and not about a predicate that says yes to everything."""
        self.assertIsNotNone(
            worktree_differential.undifferentiable_reason("make setup | tee log")
        )


class TestSkillProse(unittest.TestCase):
    """What the shipped steps must say. Each pin names a fail-open."""

    @classmethod
    def setUpClass(cls):
        _, cls.body = _split_frontmatter_body(_SKILL_MD.read_text(encoding="utf-8"))

    def _step(self, start: str, *ends: str) -> str:
        from _md_helpers import _slice

        return _slice(self.body, start, ends)

    def test_declare_rule_names_all_three_conditions(self):
        """`no_gap` alone is fail-open twice over: identical-but-failing legs,
        and a degraded placement that hides a real gap."""
        step = self._step("## Step 5", "## Step 6")
        for needle in ("no_gap", "worktree_exit", "DEGRADED PLACEMENT"):
            with self.subTest(needle=needle):
                self.assertIn(needle, step, f"Step 5's declare rule drops {needle!r}")

    def test_detection_treats_a_degraded_measurement_as_inconclusive(self):
        step = self._step("## Step 2", "## Step 3")
        self.assertIn("DEGRADED PLACEMENT", step)
        self.assertIn("inconclusive", step.lower())

    def test_detection_refuses_a_failing_primary_leg(self):
        """A declared command that does not pass where it should makes the
        divergence unattributable to provisioning."""
        step = self._step("## Step 2", "## Step 3")
        self.assertIn("primary_exit", step)

    def test_consent_discloses_the_primary_checkout_side_effect(self):
        """The differential runs its command in cwd as WELL as the throwaway,
        so verification installs into the customer's real working tree. Consent
        for that has to be asked before it happens."""
        step = self._step("## Step 4", "## Step 5")
        self.assertIn("primary", step)
        for needle in ("both", "side effect"):
            with self.subTest(needle=needle):
                self.assertIn(needle, step.lower())

    def test_refusal_step_declares_nothing_and_asks_the_customer(self):
        step = self._step("## Step 6", "## Step 7")
        lowered = step.lower()
        self.assertIn("refuse", lowered)
        self.assertIn("declare nothing", lowered)
        self.assertIn("author", lowered)

    def test_every_differential_invocation_passes_smm_dir_and_root(self):
        """`--smm-dir` is required=True (argparse exits 2 without it) and is
        load-bearing past parsing: it resolves the shared env both legs run
        under, and the throwaway's teardown needs it. `--cwd` must be the
        checkout ROOT — the differential refuses a subdirectory, because the
        two legs would then differ by position as well as by checkout.

        Read per fenced block rather than per line: a real invocation wraps
        across lines, so a line-scoped check would report the flags missing
        from the line that names the script and pass on the one that carries
        them.
        """
        blocks = [b for b in self.body.split("```") if "worktree_differential" in b]
        self.assertGreaterEqual(len(blocks), 2, "detect and verify are both calls")
        for block in blocks:
            with self.subTest(block=" ".join(block.split())[:70]):
                self.assertIn("--smm-dir", block)
                self.assertIn("--cwd", block)

    def test_the_length_refusal_names_the_schema_cap(self):
        """Over the cap the skill asks for a script path instead of truncating —
        the measured spike's own conclusion."""
        import system_context_schema

        step = self._step("## Step 7", "## Step 8")
        self.assertIn(str(system_context_schema.STACK_FIELD_MAXLENGTH), step)

    def test_scope_report_names_the_single_verified_command(self):
        """One project holds both checkout-invariant and checkout-variant
        artifacts, and there is only one field to declare into."""
        step = self._step("## Step 8")
        self.assertIn("not verified", step.lower())

    def test_prose_is_project_agnostic(self):
        """The plugin's own script paths are elided first, and only those.

        A leak is a predicate on a USER path, not on the plugin's own — this
        skill cannot drive the tools it drives without naming their files, the
        same carve-out the assign-skill prose suite makes. Everything outside a
        `${CLAUDE_PLUGIN_ROOT}/...` token is scanned RAW: the shared vocabulary
        is deliberately mixed-case, so a `.lower()` copy silently stops matching
        several members and degrades the guard to inert.
        """
        scanned = _PLUGIN_PATH_RE.sub("<plugin script>", self.body)
        assert_project_agnostic(self, scanned, "xp-scaffold-worktree SKILL.md")

    def test_prose_names_no_single_language(self):
        """No language is the rule — the skill runs whatever the project
        declared and reads its repo with judgment, neither of which needs a
        language named.

        Word-boundary matched, which is also what exempts `python3`: the plugin
        is written in it and requires it on PATH, so its own runtime prefix says
        nothing about the customer's project — while a bare `Python` in the
        prose still fails.
        """
        for token in ("python", "javascript", "typescript", "rust", "golang", "ruby"):
            with self.subTest(token=token):
                self.assertIsNone(
                    re.search(rf"(?<![\w-]){token}(?![\w-])", self.body, re.I),
                    f"SKILL.md names {token!r} — the plugin ships to projects "
                    f"in any language",
                )


class TestSkillIsInline(unittest.TestCase):
    """The close skills fork; this one must not — it drives an interactive
    confirmation and a customer-visible refusal."""

    def test_frontmatter_does_not_declare_a_fork(self):
        frontmatter, _ = _split_frontmatter_body(_SKILL_MD.read_text(encoding="utf-8"))
        self.assertNotIn("context: fork", frontmatter)


class TestPreloadAddsNothingToTheSharedBase(unittest.TestCase):
    """The shared preload base is at 492 of a 500-line cap, and the size pin
    globs only source files — so crossing it there crosses SILENTLY. This
    skill's preload therefore SOURCES the base and adds nothing to it.
    """

    def test_the_shared_base_is_only_sourced(self):
        text = _PRELOAD.read_text(encoding="utf-8")
        self.assertIn("_preload_base.sh", text)
        self.assertIn("source ", text)

    def test_the_shared_base_stays_under_its_cap(self):
        base = _PLUGIN_ROOT / "skills" / "_preload_base.sh"
        lines = len(base.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(
            lines,
            500,
            f"_preload_base.sh is {lines} lines — the size pin does not scan it, "
            f"so nothing else reports this",
        )


class TestPreloadIsExecutable(unittest.TestCase):
    def test_preload_runs_as_a_program(self):
        self.assertTrue(_PRELOAD.is_file())
        result = subprocess.run(["bash", "-n", str(_PRELOAD)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == "__main__":
    unittest.main()
