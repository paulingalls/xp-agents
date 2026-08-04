#!/usr/bin/env python3
"""Throwaway: validity checks for the hook-side skill-preload injector.

The channel is already proven — a marker minted on `PreToolUse:Bash` reached the
model byte-identically. What these checks pin is the part that can be wrong
QUIETLY: resolving the right skill, running the command its own `SKILL.md` names,
and doing it once.

Three of them exist because plan review named a specific way the design could
misbehave, and each would pass a naive implementation:

- **Idempotence is a design requirement, not a nicety.** A chunk-read SKILL.md
  fires PreToolUse repeatedly (14 firings across two skills in story-003's
  corpus). `skills/xp-assign/scripts/preload.sh` is invoked as `--consume-gate`
  and consumes a marker, so re-running it would consume a gate per chunk.
- **The command must come from the `!` line, never a hardcoded filename.** Two of
  the sixteen shipped skills do not say `preload.sh` — one takes an argument, one
  is a different script entirely — and one of those two is the most-used skill.
- **The resolved dir must be under the plugin root.** The handler executes a
  command read out of a file whose path arrived in `tool_input.command`.

Deleted with the rest of the rig at sprint close. Run explicitly:
    pytest plugins/xp-agents/spike/test_skill_inject.py
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SPIKE = Path(__file__).parent
_HANDLER = _SPIKE / "_skill_inject.py"
_REAL_SKILLS = _SPIKE.parent / "skills"


def _payload(command: str, session: str = "s1") -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "session_id": session,
            "cwd": "/tmp/x",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    )


def _run(payload: str, records: Path, plugin_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_HANDLER)],
        input=payload.encode("utf-8"),
        capture_output=True,
        env={
            "XP_SPIKE_DIR": str(records),
            "CLAUDE_PLUGIN_ROOT": str(plugin_root),
            "PATH": "/usr/bin:/bin",
        },
    )


def _injected(proc: subprocess.CompletedProcess) -> str | None:
    """The injected context, or None when this firing injected nothing."""
    assert proc.returncode == 0, (
        f"handler must exit 0, got {proc.returncode}: {proc.stderr.decode()[:400]}"
    )
    if not proc.stdout.strip():
        return None
    out = json.loads(proc.stdout.decode("utf-8"))
    return out["hookSpecificOutput"]["additionalContext"]


def _records(records: Path) -> list[dict]:
    path = records / "skill_inject.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _fake_plugin(root: Path, skill: str, preload_line: str, script: str) -> None:
    """A plugin tree whose skill names `preload_line` and ships `script`."""
    sdir = root / "skills" / skill
    (sdir / "scripts").mkdir(parents=True, exist_ok=True)
    (sdir / "SKILL.md").write_text(
        f"---\nname: {skill}\n---\n\n!`{preload_line}`\n\n# Body\n"
    )
    name = preload_line.split("${CLAUDE_SKILL_DIR}/")[1].split("`")[0].split()[0]
    target = sdir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(script)
    target.chmod(0o755)


class TestSkillResolution(unittest.TestCase):
    def test_extracts_the_skill_from_every_real_shipped_path(self) -> None:
        # Not just the one command shape story-003's corpus happens to hold.
        sys.path.insert(0, str(_SPIKE))
        import _skill_inject

        skills = sorted(
            p.parent.name
            for p in _REAL_SKILLS.glob("*/SKILL.md")
            if p.read_text().lstrip().startswith("---")
        )
        self.assertGreaterEqual(len(skills), 16, "expected the real skill tree")
        for skill in skills:
            path = f"/plug/skills/{skill}/SKILL.md"
            for shape in (
                f"sed -n '1,240p' {path}",
                f"cat {path}",
                f"head -50 {path}",
                f"python3 -c \"print(open('{path}').read())\"",
            ):
                self.assertEqual(
                    _skill_inject.skill_dir_from_command(shape),
                    Path(f"/plug/skills/{skill}"),
                    f"failed on {skill} with shape {shape[:30]}",
                )

    def test_a_command_with_no_skill_path_injects_nothing_and_records_nothing(
        self,
    ) -> None:
        # Otherwise every shell call in the session looks like a skill invocation.
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            _fake_plugin(root, "s", "${CLAUDE_SKILL_DIR}/scripts/p.sh", "#!/bin/sh\n")
            r = _run(_payload("git status"), rec, root)
            self.assertIsNone(_injected(r))
            self.assertEqual(_records(rec), [])


class TestRunsTheCommandTheSkillNames(unittest.TestCase):
    def test_honours_a_line_that_is_not_preload_sh(self) -> None:
        # 2 of the 16 shipped skills do not say scripts/preload.sh. A hardcoded
        # filename passes every other check here and silently mishandles them.
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            _fake_plugin(
                root,
                "odd",
                "${CLAUDE_SKILL_DIR}/scripts/check_session_needs.sh",
                "#!/bin/sh\necho ODD-SCRIPT-RAN\n",
            )
            cmd = _payload(f"cat {root}/skills/odd/SKILL.md")
            ctx = _injected(_run(cmd, rec, root))
            self.assertIsNotNone(ctx)
            self.assertIn("ODD-SCRIPT-RAN", ctx)

    def test_passes_through_the_arguments_the_line_carries(self) -> None:
        # One shipped line is `preload.sh --consume-gate`. Dropping the argument
        # changes what the preload does.
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            _fake_plugin(
                root,
                "args",
                "${CLAUDE_SKILL_DIR}/scripts/preload.sh --consume-gate",
                '#!/bin/sh\necho "ARGS:$*"\n',
            )
            cmd = _payload(f"cat {root}/skills/args/SKILL.md")
            ctx = _injected(_run(cmd, rec, root))
            self.assertIn("ARGS:--consume-gate", ctx)

    def test_a_failing_preload_injects_nothing_and_records_the_failure(self) -> None:
        # Injecting a partial or empty payload that reads as success is the one
        # outcome that corrupts the AC rather than failing it.
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            _fake_plugin(
                root,
                "boom",
                "${CLAUDE_SKILL_DIR}/scripts/preload.sh",
                "#!/bin/sh\necho partial\nexit 3\n",
            )
            self.assertIsNone(
                _injected(_run(_payload(f"cat {root}/skills/boom/SKILL.md"), rec, root))
            )
            entry = _records(rec)[0]
            self.assertEqual(entry["exit_status"], 3)
            self.assertFalse(entry["injected"])


class TestIdempotence(unittest.TestCase):
    def test_repeated_firings_run_the_preload_once(self) -> None:
        # A chunk-read fires PreToolUse repeatedly. xp-assign's preload consumes
        # a gate marker, so re-running it would consume one per chunk.
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            counter = Path(td) / "runs"
            _fake_plugin(
                root,
                "once",
                "${CLAUDE_SKILL_DIR}/scripts/preload.sh",
                f'#!/bin/sh\necho ran >> "{counter}"\necho STATE\n',
            )
            cmd = _payload(f"cat {root}/skills/once/SKILL.md")
            first = _injected(_run(cmd, rec, root))
            rest = [_injected(_run(cmd, rec, root)) for _ in range(3)]
            self.assertIsNotNone(first)
            self.assertEqual(
                rest, [None, None, None], "only the first firing may inject"
            )
            self.assertEqual(
                counter.read_text().count("ran"), 1, "preload must run exactly once"
            )

    def test_a_different_session_injects_again(self) -> None:
        # The once-marker is scoped to (skill, session). A new session is a new
        # invocation and must get its state, or the design breaks on resume.
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            _fake_plugin(
                root,
                "sess",
                "${CLAUDE_SKILL_DIR}/scripts/preload.sh",
                "#!/bin/sh\necho STATE\n",
            )
            c = f"cat {root}/skills/sess/SKILL.md"
            self.assertIsNotNone(_injected(_run(_payload(c, "A"), rec, root)))
            self.assertIsNone(_injected(_run(_payload(c, "A"), rec, root)))
            self.assertIsNotNone(_injected(_run(_payload(c, "B"), rec, root)))


class TestExecutionSurface(unittest.TestCase):
    def test_refuses_a_skill_dir_outside_the_plugin_root(self) -> None:
        # The handler executes a command read from a file whose path arrived in
        # tool_input.command. Without this, any /skills/<n>/SKILL.md-shaped token
        # makes the hook run that file's ! line.
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            root.mkdir(parents=True, exist_ok=True)
            evil = Path(td) / "evil"
            _fake_plugin(
                evil,
                "pwn",
                "${CLAUDE_SKILL_DIR}/scripts/preload.sh",
                "#!/bin/sh\necho PWNED\n",
            )
            r = _run(_payload(f"cat {evil}/skills/pwn/SKILL.md"), rec, root)
            self.assertIsNone(_injected(r))
            entry = _records(rec)[0]
            self.assertFalse(entry["injected"])
            self.assertIn("outside plugin root", entry["reason"])


class TestMarkerAndSuppression(unittest.TestCase):
    def test_marker_is_fresh_and_not_taken_from_the_environment(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            _fake_plugin(
                root,
                "m",
                "${CLAUDE_SKILL_DIR}/scripts/preload.sh",
                "#!/bin/sh\necho S\n",
            )
            c = f"cat {root}/skills/m/SKILL.md"
            a = _injected(_run(_payload(c, "A"), rec, root))
            b = _injected(_run(_payload(c, "B"), rec, root))
            markers = [e["marker"] for e in _records(rec)]
            self.assertEqual(len(set(markers)), 2, "each invocation mints its own")
            for m, ctx in zip(markers, (a, b), strict=True):
                self.assertIn(m, ctx)

    def test_suppressed_mode_records_the_marker_but_injects_nothing(self) -> None:
        # This is run G0's control. Unwiring the handler instead would leave the
        # marker record present only when injection is also on, so a model that
        # read the record could fake a pass.
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            _fake_plugin(
                root,
                "sup",
                "${CLAUDE_SKILL_DIR}/scripts/preload.sh",
                "#!/bin/sh\necho S\n",
            )
            env_extra = {"XP_SPIKE_SUPPRESS_INJECT": "1"}
            proc = subprocess.run(
                [sys.executable, str(_HANDLER)],
                input=_payload(f"cat {root}/skills/sup/SKILL.md").encode(),
                capture_output=True,
                env={
                    "XP_SPIKE_DIR": str(rec),
                    "CLAUDE_PLUGIN_ROOT": str(root),
                    "PATH": "/usr/bin:/bin",
                    **env_extra,
                },
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, b"", "suppressed mode must emit nothing")
            entry = _records(rec)[0]
            self.assertTrue(entry["marker"], "the marker is still recorded")
            self.assertFalse(entry["injected"])
            self.assertTrue(entry["suppressed"])


class TestNeverBreaksTheHost(unittest.TestCase):
    def test_unparseable_stdin_exits_zero_and_injects_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            root.mkdir(parents=True)
            r = _run("not json <<<", rec, root)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, b"")

    def test_missing_skill_md_records_and_injects_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            (root / "skills" / "ghost").mkdir(parents=True)
            r = _run(_payload(f"cat {root}/skills/ghost/SKILL.md"), rec, root)
            self.assertIsNone(_injected(r))
            self.assertFalse(_records(rec)[0]["injected"])

    def test_a_skill_md_with_no_preload_line_injects_nothing(self) -> None:
        # 2 of 18 shipped skills carry no ! line. They are not failures.
        with tempfile.TemporaryDirectory() as td:
            root, rec = Path(td) / "plug", Path(td) / "rec"
            sdir = root / "skills" / "bare"
            sdir.mkdir(parents=True)
            (sdir / "SKILL.md").write_text("---\nname: bare\n---\n\n# No preload\n")
            r = _run(_payload(f"cat {sdir}/SKILL.md"), rec, root)
            self.assertIsNone(_injected(r))
            entry = _records(rec)[0]
            self.assertFalse(entry["injected"])
            self.assertIn("no preload line", entry["reason"])


if __name__ == "__main__":
    unittest.main()
