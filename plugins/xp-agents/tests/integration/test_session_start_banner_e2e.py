#!/usr/bin/env python3
"""The two SessionStart channels agree — proven through the real hook.

`tests/hooks/test_session_start_honesty.py` pins the same property in-process,
with `hook_output` patched. That is the right place for the branch logic, but it
cannot see whether the emitted JSON actually carries both fields: a change to
`hook_io.hook_output` could drop `systemMessage` entirely and every in-process
row would still pass, because they read the call's arguments rather than its
output.

So this drives `session_start.py` as a subprocess and parses the JSON a host
would parse. One observation of a subprocess by hand is not proof — that is the
trap discovery `d49c2d1fb85b` fell into — so the check lives here as a test.

The failing arm is created by pointing SMM_DIR at a path that cannot be a valid
SMM, which is what a full disk, a bad symlink or a permissions problem produce
in the field.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from conftest import _IntegrationTestCase

_ACTIVE_CLAIM = "active"
_KICKOFF_INVITE = "/xp-kickoff"


class TestTheEmittedBannerAgreesWithTheContext(_IntegrationTestCase):
    """SessionStart run the way the host runs it."""

    def _emit(self, smm_dir_value: str) -> tuple[str, str]:
        """Run the real hook with SMM_DIR pinned, and parse what it printed.

        Returns (additionalContext, systemMessage). Both are asserted present
        rather than defaulted: a missing user-facing line is precisely the
        failure this story exists to prevent, so it must not read as an empty
        string that trivially satisfies every "does not claim active" row.
        """
        env = self._env_with_plugin_root()
        env["SMM_DIR"] = smm_dir_value
        result = subprocess.run(
            ["python3", str(self.scripts_dir / "session_start.py")],
            input=json.dumps({"session_id": "e2e", "source": "startup"}),
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        specific = payload["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "SessionStart")
        return (
            self._assert_not_none(specific.get("additionalContext"), "no context"),
            self._assert_not_none(payload.get("systemMessage"), "no systemMessage"),
        )

    def test_an_unusable_smm_dir_is_reported_to_both_audiences(self):
        """The measured defect, end to end: the agent read "disabled" while the
        user read "active" and was invited into the unenforced session."""
        context, message = self._emit("/dev/null/not-a-directory")
        self.assertIn("SMM init failed", context)
        self.assertNotIn(_ACTIVE_CLAIM, message)
        self.assertNotIn(_KICKOFF_INVITE, message)

    def test_the_disabled_banner_still_reaches_the_user_at_all(self):
        """Suppressing the line would satisfy the row above while leaving the
        user with nothing to act on."""
        _, message = self._emit("/dev/null/not-a-directory")
        self.assertGreater(len(message.split()), 3, message)

    def test_a_usable_smm_dir_keeps_the_enforcing_banner(self):
        """Over-arming control. Without it, never emitting the active banner
        would pass every failing-arm row here."""
        context, message = self._emit(str(self.smm_dir))
        self.assertNotIn("SMM init failed", context)
        self.assertIn(_ACTIVE_CLAIM, message)

    def test_the_enforcing_banner_names_the_running_version(self):
        """The version the user reads must be the version that is running.

        Read from the manifest here, NOT through `plugin_loader.plugin_version`.
        The in-process pin (`hooks/test_session_start_honesty.py`) builds its
        expected banner from that same function, so it is self-consistent by
        construction: if the loader ever returned the wrong string, both sides
        would move together and the row would stay green. Comparing against the
        file on disk is what makes this an independent check rather than a
        tautology.

        Deliberately not asserting a literal like "5.8.0" — that would redden on
        every release and get "fixed" by pasting in the new number, which trains
        exactly the wrong reflex. The claim is agreement between two sources, not
        a particular value.
        """
        manifest = json.loads(
            (_PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text()
        )
        version = manifest["version"]
        self.assertTrue(version, "the manifest carries no version to compare against")
        _, message = self._emit(str(self.smm_dir))
        self.assertIn(
            f"v{version}",
            message,
            f"banner does not name the manifest's version {version!r}: {message!r}",
        )
