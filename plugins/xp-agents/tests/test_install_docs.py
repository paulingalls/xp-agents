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
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _paths import _PLUGIN_ROOT

_README = _PLUGIN_ROOT.parents[1] / "README.md"

# The placeholder the documented local-path command carries. Pinned as a
# constant because the E2E substitutes it; a rename that slipped past would
# quietly turn that substitution into a no-op.
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


if __name__ == "__main__":
    unittest.main()
