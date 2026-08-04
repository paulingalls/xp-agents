#!/usr/bin/env python3
"""Throwaway: validity checks for the payload-field tabulator.

The tabulator's output IS story-007's evidence for the compatibility table, so a
wrong cell is a wrong verdict. Every check here fails against a specific
plausible-but-wrong implementation, named in its comment.

The load-bearing one is three-state-ness. Measured in the real corpus:
`agent_type`/`agent_id` are ABSENT on top-level PreToolUse/PostToolUse and
'default' on subagent-scoped firings of the SAME events. A two-state
present/absent table is wrong in both directions there — "present on
PostToolUse" is false at top level, "absent" is false when nested — so a
collapse to two states must fail loudly rather than pick a side.

Deleted with the rest of the rig at sprint close. Run explicitly:
    pytest plugins/xp-agents/spike/test_tabulate.py
(`pytest.ini` sets `testpaths` to the tests dir, so the default run skips it.)
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import tabulate_fields

ALWAYS = tabulate_fields.ALWAYS
SOME = tabulate_fields.SOME_FIRINGS
NEVER = tabulate_fields.NEVER
NOT_OBSERVED = tabulate_fields.NOT_OBSERVED


def _corpus(tmp: Path, run: str, payloads: list[dict]) -> None:
    """Write payloads into the REAL nested layout: run-X/payloads/payloads/.

    The layout is part of what this pins. The plan originally had it one level
    off and would have flat-merged two runs' index files over each other.
    """
    out = tmp / run / "payloads" / "payloads"
    out.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(payloads):
        name = f"{i:024d}-{1000 + i}-{p['hook_event_name']}.raw"
        (out / name).write_bytes(json.dumps(p).encode("utf-8"))


class TestThreeStates(unittest.TestCase):
    def test_a_field_on_only_some_firings_is_neither_always_nor_never(self) -> None:
        # The real finding. A two-state table must not be able to express this
        # corpus, so a collapse to present/absent fails here.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _corpus(
                tmp,
                "run-1",
                [
                    {
                        "hook_event_name": "PostToolUse",
                        "cwd": "/x",
                        "tool_name": "Bash",
                    },
                    {
                        "hook_event_name": "PostToolUse",
                        "cwd": "/x",
                        "tool_name": "Bash",
                        "agent_type": "default",
                        "agent_id": "abc",
                    },
                ],
            )
            table = tabulate_fields.build_table(tmp)
            self.assertEqual(table["PostToolUse"]["agent_type"], SOME)
            self.assertEqual(table["PostToolUse"]["agent_id"], SOME)
            # Controls: a field on every firing, and one on none.
            self.assertEqual(table["PostToolUse"]["cwd"], ALWAYS)
            self.assertEqual(table["PostToolUse"]["source"], NEVER)

    def test_present_is_never_reported_absent_or_vice_versa(self) -> None:
        # Guards an inverted presence check, which would pass every count-based
        # assertion while reporting the exact opposite of the truth.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _corpus(
                tmp,
                "run-1",
                [{"hook_event_name": "SessionStart", "cwd": "/x", "source": "startup"}],
            )
            table = tabulate_fields.build_table(tmp)
            self.assertEqual(table["SessionStart"]["source"], ALWAYS)
            self.assertEqual(table["SessionStart"]["stop_hook_active"], NEVER)

    def test_an_event_with_zero_captures_is_reported_not_observed(self) -> None:
        # A dropped row reads downstream as "checked and fine" — the single
        # failure mode this milestone exists to avoid.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _corpus(tmp, "run-1", [{"hook_event_name": "Stop", "cwd": "/x"}])
            table = tabulate_fields.build_table(tmp, registered=["Stop", "PreCompact"])
            self.assertIn("PreCompact", table)
            self.assertEqual(table["PreCompact"], NOT_OBSERVED)


class TestExtraFields(unittest.TestCase):
    def test_fields_absent_from_our_table_are_reported(self) -> None:
        # A hardwired-empty section would pass any check that only looks at the
        # 14 known fields, so assert a specific unknown key is surfaced.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _corpus(
                tmp,
                "run-1",
                [
                    {
                        "hook_event_name": "SessionStart",
                        "cwd": "/x",
                        "turn_id": "t1",
                        "permission_mode": "never",
                    }
                ],
            )
            extra = tabulate_fields.extra_fields(tmp)
            self.assertIn("turn_id", extra)
            self.assertIn("permission_mode", extra)
            # A field we DO know about must not leak into the extras section.
            self.assertNotIn("cwd", extra)


class TestFiringOrder(unittest.TestCase):
    def test_decisive_fields_are_reported_in_firing_order_not_as_a_set(self) -> None:
        # A set hides the trap: firings AFTER SubagentStop still carry the
        # finished subagent's agent_id. Order is what makes that visible.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _corpus(
                tmp,
                "run-1",
                [
                    {"hook_event_name": "PreToolUse", "cwd": "/x"},
                    {
                        "hook_event_name": "SubagentStop",
                        "cwd": "/x",
                        "agent_id": "dead",
                    },
                    {
                        "hook_event_name": "PostToolUse",
                        "cwd": "/x",
                        "agent_id": "dead",
                    },
                ],
            )
            seq = tabulate_fields.firing_sequence(tmp)
            self.assertEqual(
                [(e["event"], e["agent_id"]) for e in seq],
                [
                    ("PreToolUse", None),
                    ("SubagentStop", "dead"),
                    ("PostToolUse", "dead"),
                ],
            )

    def test_multiple_runs_are_namespaced_not_merged(self) -> None:
        # Two runs' records must stay attributable; flat-merging was a real
        # defect in the first draft of the plan.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _corpus(tmp, "run-1", [{"hook_event_name": "Stop", "cwd": "/a"}])
            _corpus(tmp, "run-2", [{"hook_event_name": "Stop", "cwd": "/b"}])
            seq = tabulate_fields.firing_sequence(tmp)
            self.assertEqual({e["run"] for e in seq}, {"run-1", "run-2"})


class TestEmptyCorpusFailsLoud(unittest.TestCase):
    """A silently-empty corpus is the one defect class this milestone can't ship.

    An all-`not-observed` table is well-formed, complete-looking markdown that
    reads exactly like "no hook ever fired on any event" — and the dump tells
    story-007's reader to re-run the tabulator, on a machine where the
    out-of-tree corpus may be absent or moved. Zero captures must therefore
    raise, not render.
    """

    def test_missing_corpus_raises_instead_of_a_full_not_observed_table(self) -> None:
        with (
            tempfile.TemporaryDirectory() as td,
            self.assertRaises(FileNotFoundError),
        ):
            tabulate_fields.render(Path(td) / "not-there", registered=["Stop"])

    def test_a_run_dir_at_the_wrong_nesting_depth_raises(self) -> None:
        # The plan had this layout one level off. Unguarded, that mistake reads
        # as "every event unobserved" rather than as "I found no corpus".
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wrong = tmp / "run-1" / "payloads"  # missing the second `payloads`
            wrong.mkdir(parents=True)
            (wrong / "0-1-Stop.raw").write_bytes(b'{"hook_event_name": "Stop"}')
            with self.assertRaises(FileNotFoundError):
                tabulate_fields.build_table(tmp)


class TestRegisteredEvents(unittest.TestCase):
    def test_reads_every_event_name_from_the_hooks_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            hooks = Path(td) / "hooks.json"
            hooks.write_text(json.dumps({"hooks": {"Stop": [], "SessionStart": []}}))
            self.assertEqual(
                tabulate_fields.registered_events(hooks), ["SessionStart", "Stop"]
            )

    def test_unreadable_hooks_file_raises_rather_than_dropping_every_row(self) -> None:
        # Returning [] made main() fall back to observed-only events, silently
        # deleting exactly the unfired rows this function exists to add — and
        # a dropped row reads downstream as "checked and fine".
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(OSError):
                tabulate_fields.registered_events(Path(td) / "absent.json")
            bad = Path(td) / "bad.json"
            bad.write_text("{not json")
            with self.assertRaises(json.JSONDecodeError):
                tabulate_fields.registered_events(bad)
            no_hooks = Path(td) / "no-hooks.json"
            no_hooks.write_text(json.dumps({"name": "x"}))
            with self.assertRaises(ValueError):
                tabulate_fields.registered_events(no_hooks)


class TestRender(unittest.TestCase):
    def test_every_registered_event_gets_a_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _corpus(tmp, "run-1", [{"hook_event_name": "Stop", "cwd": "/x"}])
            md = tabulate_fields.render(tmp, registered=["Stop", "TeammateIdle"])
            self.assertIn("Stop", md)
            self.assertIn("TeammateIdle", md)
            self.assertIn(NOT_OBSERVED, md)

    def test_a_run_with_zero_captures_is_named_not_silently_dropped(self) -> None:
        # Same reason `unparseable` exists, one level up: a dropped RUN shrinks
        # the denominator far harder than a dropped file, and it is not
        # hypothetical — the real corpus has one (the untrusted-plugin control,
        # whose hooks were skipped silently). Unnamed, a reader cannot tell that
        # run from one lost to a layout mistake.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _corpus(tmp, "run-1", [{"hook_event_name": "Stop", "cwd": "/x"}])
            (tmp / "run-2" / "payloads").mkdir(parents=True)
            self.assertEqual(tabulate_fields.runs_without_captures(tmp), ["run-2"])
            self.assertIn("run-2", tabulate_fields.render(tmp, registered=["Stop"]))

    def test_a_decisive_field_sent_as_json_null_renders_as_present(self) -> None:
        # Same falsy-vs-absent trap the three-state table exists to avoid, one
        # section further down: filtering the firing list on `is not None` prints
        # an explicit `null` identically to a field the host never sent. On a
        # DECISIVE field that is a false reading of the sprint's whole question.
        # (`False` already survives — this pins the remaining hole.)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _corpus(
                tmp,
                "run-1",
                [
                    {"hook_event_name": "Stop", "stop_hook_active": None},
                    {"hook_event_name": "Stop", "stop_hook_active": False},
                    {"hook_event_name": "Stop"},
                ],
            )
            lines = [
                x
                for x in tabulate_fields.render(tmp, registered=["Stop"]).splitlines()
                if x.startswith("- run-1 Stop:")
            ]
            self.assertEqual(
                lines,
                [
                    "- run-1 Stop: stop_hook_active=None",
                    "- run-1 Stop: stop_hook_active=False",
                    "- run-1 Stop: (none present)",
                ],
            )

    def test_unparseable_capture_is_reported_not_skipped(self) -> None:
        # A corrupt file silently ignored would shrink the denominator and could
        # turn a `some-firings` into an `always`.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _corpus(tmp, "run-1", [{"hook_event_name": "Stop", "cwd": "/x"}])
            bad = tmp / "run-1" / "payloads" / "payloads" / "999-1-Stop.raw"
            bad.write_bytes(b"not json <<<")
            self.assertEqual(tabulate_fields.unparseable(tmp), [str(bad)])


if __name__ == "__main__":
    unittest.main()
