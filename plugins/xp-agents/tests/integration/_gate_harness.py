#!/usr/bin/env python3
"""The one harness for driving `emit_gate_commands`, replacing three.

WHY ONE, AND WHY THIS SHAPE. Three near-identical `_seed`/`_resolve` pairs
grew in `test_close_gate_command_hygiene`, `test_story_close_surface_gate` and
`test_free_close_surface_gate`. They did not merely duplicate — they
DISAGREED, and the disagreement hid a shipped defect:

  * this one passes the command by ENVIRONMENT,
  * the other two interpolated it into the `bash -c` source.

An interpolating harness CANNOT express a newline-, quote- or
separator-bearing command: splicing `pytest -q\\n; echo X` into the script
makes the TEST forge the second shell line, so the assertion proves nothing
about the code under test. The block's safety properties are *entirely* about
those inputs, so two of the three harnesses were structurally incapable of
asserting the thing they existed to assert. A close review found the surviving
hole by running the shipped function by hand rather than by reading a test.

So the consolidation is not tidying. The env-passing shape is the only one
that can carry the inputs, and it is the shape kept here.

CONSEQUENCE FOR THE MIGRATION: an assertion that changes result when it moves
onto this harness is a FINDING — it was passing because its input was mangled
— and must be reported and fixed, never smoothed over. A behaviour-preserving
refactor's proof is the existing checks passing unchanged; here the checks'
input channel is what changed, so that proof does not apply.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT

SURFACE_MODULE = _PLUGIN_ROOT / "skills" / "_preload_surface.sh"

# Deliberately not a real runner name: an assertion that matches this string
# cannot be satisfied by some other pytest invocation leaking through.
FULL = "pytest -n auto THE-WHOLE-SUITE"

CLAIMED = "src/cli/main.py"


def surface(name: str, **overrides: object) -> dict:
    """A schema-valid surface. `paths`/`command` arrive via overrides.

    Defaults carry NEITHER, matching every real project on disk — the standing
    trap is that this repo declares no surface `paths`, so an assertion that
    forgets to seed one runs against an empty selection and passes vacuously.
    """
    base: dict = {"name": name, "signals": ["detected"], "status": "covered"}
    base.update(overrides)
    return base


def system_context(surfaces: list[dict] | None, test_command: str = FULL) -> dict:
    doc: dict = {
        "product": "x",
        "architecture_overview": "x",
        "stack": {"languages": ["Python"], "test_command": test_command},
        "modules": [],
        "conventions": [],
        "principles": [],
        "project_specific": [],
    }
    if surfaces is not None:
        doc["acceptance_surfaces"] = surfaces
    return doc


def sprint(file_domain: list[str]) -> dict:
    return {
        "sprint_id": "sprint-test",
        "goal": "gate",
        "started": "2026-08-03",
        "milestone": "test",
        "stories": [
            {
                "id": "story-001",
                "title": "Test",
                "status": "closing",
                "dependencies": [],
                "milestone_ref": "test",
                "design_sources": "test",
                "context": "test",
                "file_domain": file_domain,
                "interface_contracts": [],
                "acceptance_criteria": ["test"],
            }
        ],
    }


class GateHarness(unittest.TestCase):
    """Drives `emit_gate_commands` through the real shell module and the real
    `surface-commands` CLI — no story-shaped git branch required."""

    def seed(
        self,
        surfaces: list[dict] | None,
        *,
        test_command: str = FULL,
        file_domain: list[str] | None = None,
    ) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        smm = tmp / "data" / "proj" / "smm"
        smm.mkdir(parents=True)
        (smm / "events.jsonl").write_text("")
        (smm / "system_context.json").write_text(
            json.dumps(system_context(surfaces, test_command))
        )
        if file_domain is not None:
            (smm / "sprint.json").write_text(json.dumps(sprint(file_domain)))
        return smm

    def resolve(self, smm: Path, *, paths: str = CLAIMED, full: str = FULL) -> str:
        """Run `emit_gate_commands`, values travelling by ENV — see module docstring.

        Never interpolate `paths` or `full` into the script. A newline or `;`
        in `full` is the whole point of the safety assertions, and splicing it
        into the source proves nothing about the producer.
        """
        script = (
            f'PLUGIN_ROOT="{_PLUGIN_ROOT}"; SMM_DIR="{smm}"; '
            f'source "{SURFACE_MODULE}"; '
            'emit_gate_commands "$XP_T_PATHS" "$XP_T_FULL"'
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "SMM_DIR": str(smm),
                "XP_T_PATHS": paths,
                "XP_T_FULL": full,
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    @staticmethod
    def commands(stdout: str) -> list[str]:
        """The `- ` lines under the heading, STOPPING at the next markdown heading.

        Reading to EOF instead would swallow the shared close-pipeline
        reference's own bullets, which the preload appends after this block —
        caught by running the real preload by hand, not by a test.
        """
        lines = stdout.splitlines()
        if "### GATE_COMMANDS" not in lines:
            return []
        out: list[str] = []
        for ln in lines[lines.index("### GATE_COMMANDS") + 1 :]:
            if ln.startswith("#"):
                break
            if ln.startswith("- "):
                out.append(ln[2:])
        return out

    @staticmethod
    def scope(stdout: str) -> str:
        return next(
            ln.split("=", 1)[1]
            for ln in stdout.splitlines()
            if ln.startswith("GATE_SCOPE=")
        )
