#!/usr/bin/env python3
"""Pins for the install and trust docs.

Stories 001-004 made the plugin installable on the second harness; nothing told
a human how to do it. These rows hold the README's Install section to what was
actually measured, because the failure mode for install docs is not absence — it
is confident prose about something nobody ran.

Three claims are load-bearing and each is pinned by CONSEQUENCE rather than by
keyword, since a document can name `/hooks` while saying nothing about what
skipping it costs:

- trust failure is SILENT, so a reader who skips it gets a session with every
  gate absent and no signal;
- the minimum harness version is UNMEASURED, so no floor may be stated;
- the spawn flag is MANDATORY, because without it a persistent shell bypasses
  every gate riding the command hook.

The harness's own binary name stays a literal here and in the README, because it
is what a reader types. An audit that strips harness names from shipped prose is
right about agent and skill vocabulary and wrong about this document; these rows
are where that boundary is enforced rather than remembered.
"""

import re
import shlex
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _paths import _PLUGIN_ROOT

# Imported, not copied. These carry the harness's stdout contract and the
# isolation guarantee; a second copy would put the contract most likely to
# change under the harness in two places at once. The repo already imports
# across test modules this way — see test_lefthook_commit_gate importing from
# test_lefthook_perf_gate.
from test_marketplace_install import (
    _HARNESS,
    _PLUGIN_ID,
    _REPO_ROOT,
    _harness,
    _installed_root,
    _isolated_home,
)

_README = _REPO_ROOT / "README.md"

# The placeholder the documented local-path command carries. Pinned as a
# constant because the E2E substitutes it, and because it is the anchor that
# scopes the extraction below to a single fenced block.
_LOCAL_PATH_PLACEHOLDER = "/path/to/xp-agents"


def _readme() -> str:
    return _README.read_text(encoding="utf-8")


class TestBothHarnessInstallPathsDocumented(unittest.TestCase):
    """Each harness's complete sequence is present.

    The first harness's block predates this story; it is asserted alongside the
    second so that a future edit cannot document one by deleting the other.
    """

    def test_the_first_harness_sequence_is_still_documented(self):
        text = _readme()
        self.assertIn("claude plugin marketplace add", text)
        self.assertIn("claude plugin install xp-agents@xp-agents", text)

    def test_the_second_harness_sequence_is_documented(self):
        text = _readme()
        self.assertIn("codex plugin marketplace add", text)
        self.assertIn("codex plugin add xp-agents@xp-agents", text)

    def test_the_local_path_form_carries_the_pinned_placeholder(self):
        """The E2E substitutes this exact string; a rename must redden here."""
        self.assertIn(
            f"codex plugin marketplace add {_LOCAL_PATH_PLACEHOLDER}", _readme()
        )


class TestTrustStepIsDocumented(unittest.TestCase):
    """The trust step is pinned by CONSEQUENCE, not by keyword.

    A document can name the review command and still leave a reader believing
    that skipping it produces an error they would notice. The measured fact is
    the opposite — untrusted hooks are skipped silently — and that is the half a
    careless edit would drop, because it is the only half that is bad news.
    """

    def test_the_review_command_and_its_per_hash_scope_are_documented(self):
        text = _readme()
        self.assertIn("/hooks", text)
        self.assertIn("content hash", text)

    def test_the_re_review_after_every_update_is_documented(self):
        self.assertRegex(_readme(), r"repeated after every plugin update")

    def test_the_headless_bypass_is_documented(self):
        self.assertIn("--dangerously-bypass-hook-trust", _readme())

    def test_the_silent_skip_consequence_is_documented(self):
        """The row that matters. Naming `/hooks` without this is worse than
        silence: it implies a failure the reader would see."""
        text = _readme()
        self.assertIn("silently", text)
        self.assertRegex(
            text,
            r"no error appears|nothing tells you",
            "the docs name the trust step but not that skipping it is silent",
        )


class TestTheMandatorySpawnFlagIsDocumented(unittest.TestCase):
    """The flag is documented with the gates it protects, not as a bare rule.

    A reader who is told only "pass this flag" has no way to judge what a
    forgotten flag costs, and will treat it as boilerplate.
    """

    def test_the_flag_is_documented(self):
        self.assertIn("--disable unified_exec", _readme())

    def test_the_flag_is_stated_as_required_not_advisory(self):
        self.assertRegex(_readme(), r"required on every Codex spawn")

    def test_the_bypassed_gates_are_named(self):
        text = _readme()
        for gate in ("commit gate", "secret scan", "branch protection"):
            with self.subTest(gate=gate):
                self.assertIn(gate, text)


class TestNoUnmeasuredVersionFloor(unittest.TestCase):
    """No minimum version is claimed, AND the docs say why.

    Both halves are required. Absence of a version claim is vacuously true of a
    document that never mentions versions at all, so the positive half — that
    the floor is explicitly unestablished — is what makes the negative mean
    something. Only one version was ever installed; a version that works says
    nothing about where support began.
    """

    _FLOOR_CLAIMS = (
        r">=\s*0\.\d+",
        r"requires Codex \d",
        r"Codex \d[\d.]* or (later|newer)",
    )

    def test_no_minimum_version_is_claimed(self):
        text = _readme()
        for claim in self._FLOOR_CLAIMS:
            with self.subTest(claim=claim):
                self.assertNotRegex(text, claim)

    def test_the_docs_state_the_floor_is_unmeasured(self):
        text = _readme()
        self.assertRegex(text, r"No minimum Codex version is claimed")
        self.assertIn("nothing older was ever installed", text)

    def test_the_unknown_is_not_dressed_as_an_assurance(self):
        """An unmeasured floor must not read as 'every version works'."""
        self.assertRegex(_readme(), r"unknown, not an assurance")


def _documented_local_commands() -> list[str]:
    """The local-path harness commands, read out of the README itself.

    This is what makes the docs verified rather than merely present: the
    sequence executed below is the sequence a reader is told to type. Docs that
    drift from the commands the catalog accepts fail the suite.

    Scoped to the fenced block carrying the harness's own local registration,
    NOT to the whole file, and not merely to the placeholder. Two narrowings the
    first two runs of this test forced:

    - a file-wide scan pulls all FOUR documented lines — the two forms share an
      identical `plugin add` line — and would register and install twice;
    - the placeholder alone is not unique either — the first harness's
      `--plugin-dir` example carries it too.

    Both were caught by the assertions below rather than by inspection, which is
    the whole reason they are assertions.
    """
    anchor = f"{_HARNESS} plugin marketplace add {_LOCAL_PATH_PLACEHOLDER}"
    blocks = re.findall(r"```bash\n(.*?)```", _readme(), re.DOTALL)
    local = [b for b in blocks if anchor in b]
    if len(local) != 1:
        raise AssertionError(
            f"expected exactly one bash block carrying {anchor!r}, found {len(local)}"
        )
    return [
        line.strip()
        for line in local[0].splitlines()
        if line.strip().startswith(f"{_HARNESS} plugin")
    ]


@unittest.skipUnless(
    shutil.which(_HARNESS), f"{_HARNESS} not on PATH — install-dependent rows skip"
)
class TestTheDocumentedSequenceActuallyWorks(unittest.TestCase):
    """A reader who types the documented sequence gets a working install.

    Only the LOCAL form is executed. The published form needs the network and a
    published ref, so it is excluded here and flagged as untested in the README
    rather than implied to be proven — the same honesty the version-floor rows
    enforce.
    """

    def test_the_extraction_finds_the_whole_sequence(self):
        """Non-vacuity guard for the extraction itself.

        A regex that matched nothing would run zero commands and report green,
        so the count is asserted before anything is executed.
        """
        commands = _documented_local_commands()
        self.assertEqual(
            len(commands),
            2,
            f"expected the register+install pair, extracted {commands}",
        )
        self.assertTrue(commands[0].startswith(f"{_HARNESS} plugin marketplace add"))
        self.assertIn(_PLUGIN_ID, commands[1])

    def test_running_the_documented_commands_installs_a_loadable_plugin(self):
        env, home = _isolated_home()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        repo_root = str(_REPO_ROOT)

        commands = _documented_local_commands()
        # Stated, because `_installed_root` below reads the LAST command's
        # stdout: a step documented after the install would be measured instead
        # of it, and the row would fail somewhere unrelated to the cause.
        self.assertIn(
            _PLUGIN_ID,
            commands[-1],
            f"the install must be the last documented command, got {commands}",
        )

        add_stdout = ""
        for command in commands:
            # shlex, not `.split()`: the substituted repo root is a real path
            # and a developer's checkout may contain a space, which would
            # otherwise be handed to the harness as two arguments.
            args = [
                arg.replace(_LOCAL_PATH_PLACEHOLDER, repo_root)
                for arg in shlex.split(command)
            ][2:]  # drop the harness + `plugin`
            result = _harness(env, *args)
            self.assertEqual(
                result.returncode, 0, f"{command!r} failed: {result.stderr}"
            )
            add_stdout = result.stdout

        installed_root = _installed_root(add_stdout)
        self.assertTrue(
            installed_root.is_relative_to(Path(env["CODEX_HOME"]).resolve()),
            f"{installed_root} is not inside the isolated home",
        )
        installed_skills = sorted(p.name for p in (installed_root / "skills").iterdir())
        shipped_skills = sorted(p.name for p in (_PLUGIN_ROOT / "skills").iterdir())
        self.assertTrue(shipped_skills, "no skills shipped to compare against")
        self.assertEqual(installed_skills, shipped_skills)


if __name__ == "__main__":
    unittest.main()
