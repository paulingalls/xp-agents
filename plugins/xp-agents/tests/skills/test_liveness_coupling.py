#!/usr/bin/env python3
"""The liveness verdict is reachable only from inside the runtime it judges.

Split out of `test_preload_liveness.py` when that file crossed the 450-line band
floor. The seam is a difference in KIND, not a line count: every class left
there DRIVES a real preload subprocess and asserts what it emits, while this one
reads the shipped tree and asserts how the pieces are wired. Recording a ceiling
instead would have silenced the gate that exists to force this decision.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, _preload_script_path, discover_preload_scripts


class TestTheVerdictReachesTheModelOnlyThroughAHook(unittest.TestCase):
    """What this check can and cannot still detect, pinned as a coupling.

    Sprint-007 deleted every instruction-time `!` line, and with it the one
    caller of this check that was not a hook. What remains is a chain with a
    hook at its head: `_preload_liveness.sh` is sourced by `_preload_base.sh`,
    which runs only from `preload_injection.py`. So the verdict can be produced
    only when the runtime being judged is already running — which is exactly
    the state where it has nothing left to report.

    The obvious way to pin this is a "runtime dead, so nothing is emitted"
    assertion. That is VACUOUS: with the runtime dead the preload is never
    invoked, so `assertEqual(out, "")` passes against a do-nothing
    implementation, against a deleted check, and against a correct one alike.
    The coupling is what actually carries the claim — reintroduce ANY non-hook
    caller and this class reddens, which is the whole content of Block
    ac8ecf84d3eb.

    Two runtime states, and only one of them is still covered:

    - **running but not heartbeating** — the preload runs, the banner fires.
      Every other class in this module covers it, and it keeps earning its
      keep.
    - **not loaded at all** — nothing here fires. NOT this story's to close;
      story-009 owns it (its AC2 names the harness that silently skips
      untrusted hooks, and its AC3 forbids liveness machinery on the daily
      path, which is why no replacement channel is invented here).
    """

    _LIVENESS = "_preload_liveness.sh"
    _BASE = "_preload_base.sh"

    def _shipped_text_files(self) -> list[Path]:
        """Every shipped file that could name a script, minus this test tree."""
        out: list[Path] = []
        for sub in ("skills", "scripts", "smm", "hooks"):
            for path in (_PLUGIN_ROOT / sub).rglob("*"):
                if path.is_file() and path.suffix in {".sh", ".py", ".md", ".json"}:
                    out.append(path)
        return out

    def _sources(self, path: Path, fragment: str) -> bool:
        """Does this file SOURCE the fragment, as opposed to mentioning it?

        A substring scan is not good enough and this pin proved it on its first
        run: `_preload_markers.sh` names the liveness fragment in a comment
        about the size-cap split that produced them both, and a naive `in` test
        read that as a second caller. The distinction is the act — a `source`
        or `.` directive — not the name appearing. Keying on the mention is the
        same defect story-017 exists to catch, one layer up.
        """
        pattern = re.compile(
            rf"^\s*(?:source|\.)\s+.*{re.escape(fragment)}", re.MULTILINE
        )
        return bool(pattern.search(path.read_text(encoding="utf-8")))

    def test_the_liveness_fragment_has_exactly_one_sourcing_site(self):
        """A second caller is the only way this check reaches a non-hook path."""
        callers = sorted(
            path.relative_to(_PLUGIN_ROOT).as_posix()
            for path in self._shipped_text_files()
            if path.name != self._LIVENESS and self._sources(path, self._LIVENESS)
        )
        self.assertEqual(
            callers,
            [f"skills/{self._BASE}"],
            "the liveness fragment gained or lost a caller — if a NON-hook "
            "caller was added, Block ac8ecf84d3eb is fixed and this pin plus "
            "the three prose blocks must be rewritten to say so",
        )

    def test_every_base_consumer_is_a_preload_the_injection_hook_resolves(self):
        """The chain's other link: the base is reached only by preload scripts,
        and `test_preload_wiring` already pins that every one of those is
        resolved by the injection handler and that no SKILL.md carries an
        instruction-time line. Together those close the loop."""
        resolved = {_preload_script_path(skill) for skill in discover_preload_scripts()}
        strays = sorted(
            path.relative_to(_PLUGIN_ROOT).as_posix()
            for path in self._shipped_text_files()
            if path.name not in {self._BASE, self._LIVENESS}
            and path not in resolved
            and self._sources(path, self._BASE)
        )
        self.assertEqual(
            strays,
            [],
            "something outside the resolved preload set sources the base, so "
            f"the liveness chain may no longer start at a hook: {strays}",
        )


if __name__ == "__main__":
    unittest.main()
