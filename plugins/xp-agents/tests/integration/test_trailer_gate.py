#!/usr/bin/env python3
"""Tests for scripts/trailer_gate.py — the pre-merge Resolves-Event advisory.

The advisory is a thin reuse layer over retro_metrics' canonical eligibility
(eligible_trailer_commits + has_resolves_trailer): it surfaces the trailer
ratio at close-merge time, names the un-trailered eligible commits, and NEVER
blocks the merge. These tests pin both the pure advisory() contract and the
non-blocking wiring through close_common.cmd_merge over a real temp repo.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
from _bases import _PLUGIN_ROOT, _AssertNotNoneMixin
from _branching_fixtures import open_concern_event
from _event_fixtures import make_event
from event_schema import EVENT_TYPE_COMMIT

_CLOSE_COMMON = _PLUGIN_ROOT / "scripts" / "close_common.py"


def _code_commit(resolves: list[str], ts: str, commit_hash: str, subject: str) -> dict:
    """An eligible code commit over scripts/x.py (overlaps the open concern)."""
    return make_event(
        EVENT_TYPE_COMMIT,
        content=subject,
        ts=ts,
        files=["scripts/x.py"],
        metadata={
            "code_commit": True,
            "commit_hash": commit_hash,
            "resolves": resolves,
        },
    )


def _write_events(smm_dir: Path, events: list[dict]) -> None:
    (smm_dir / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )


class TestAdvisory(_AssertNotNoneMixin, unittest.TestCase):
    """Pure advisory() contract over a seeded events.jsonl (no merge)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.smm = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

    def test_at_or_above_threshold_returns_none(self):
        # 4 of 5 eligible commits carry trailers = 80% >= THRESHOLD → no advisory.
        import trailer_gate

        events = [open_concern_event()]
        for i in range(4):
            events.append(
                _code_commit(["aaa"], f"2026-04-05T1{i}:00:00+00:00", f"h{i}", f"c{i}")
            )
        events.append(_code_commit([], "2026-04-05T15:00:00+00:00", "h4", "no trailer"))
        _write_events(self.smm, events)
        self.assertIsNone(trailer_gate.advisory(self.smm))

    def test_advisory_is_ascii_only(self):
        # Regression (concern 92521f97fa82): the advisory is print()ed to a
        # stdout that may not be UTF-8; a non-ASCII char would raise
        # UnicodeEncodeError after the merge commits but before push/delete,
        # leaving the source merged-but-unpushed. Pin the text to pure ASCII.
        import trailer_gate

        events = [
            open_concern_event(),
            _code_commit(["aaa"], "2026-04-05T10:00:00+00:00", "hash111", "did link"),
            _code_commit(["bbb"], "2026-04-05T11:00:00+00:00", "hash222", "also link"),
            _code_commit([], "2026-04-05T12:00:00+00:00", "deadbee", "forgot trailer"),
        ]
        _write_events(self.smm, events)
        msg = self._assert_not_none(trailer_gate.advisory(self.smm))
        self.assertTrue(msg.isascii(), f"advisory must be ASCII-only: {msg!r}")

    def test_below_threshold_returns_advisory_with_ratio_and_commits(self):
        # 2 of 3 eligible = 67% < 80% → advisory names the ratio and EACH
        # un-trailered eligible commit (short hash + subject).
        import trailer_gate

        events = [
            open_concern_event(),
            _code_commit(["aaa"], "2026-04-05T10:00:00+00:00", "hash111", "did link"),
            _code_commit(["bbb"], "2026-04-05T11:00:00+00:00", "hash222", "also link"),
            _code_commit([], "2026-04-05T12:00:00+00:00", "deadbee", "forgot trailer"),
        ]
        _write_events(self.smm, events)
        msg = self._assert_not_none(trailer_gate.advisory(self.smm))
        self.assertIn("2/3", msg)
        self.assertIn("80", msg)  # the threshold is named
        # The un-trailered commit is surfaced by short hash + subject...
        self.assertIn("deadbee", msg)
        self.assertIn("forgot trailer", msg)
        # ...and the trailered ones are NOT in the un-trailered list.
        self.assertNotIn("did link", msg)
        self.assertNotIn("also link", msg)

    def test_no_eligible_commits_returns_none(self):
        # No open concern overlapping the commit → candidate gate excludes it →
        # empty denominator → no advisory (can't divide, nothing to nudge).
        import trailer_gate

        events = [
            _code_commit([], "2026-04-05T10:00:00+00:00", "h0", "orphan commit"),
        ]
        _write_events(self.smm, events)
        self.assertIsNone(trailer_gate.advisory(self.smm))


class TestCmdMergeNonBlocking(unittest.TestCase):
    """The advisory rides on cmd_merge but NEVER changes its exit code."""

    def test_sub_threshold_merge_prints_advisory_and_returns_zero(self):
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as repo_td,
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as smm_td,
        ):
            _bf.init_repo(repo_td)
            main = _bf.get_current_branch(repo_td)
            _bf.make_commit(repo_td, "feature-x", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=repo_td, capture_output=True, check=True
            )

            smm = Path(smm_td)
            _write_events(
                smm,
                [
                    open_concern_event(),
                    _code_commit(
                        ["aaa"], "2026-04-05T10:00:00+00:00", "hash111", "did link"
                    ),
                    _code_commit(
                        [], "2026-04-05T11:00:00+00:00", "deadbee", "forgot trailer"
                    ),
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(_CLOSE_COMMON),
                    "merge",
                    "--cwd",
                    repo_td,
                    "--source",
                    "feature-x",
                    "--target",
                    main,
                    "--smm-dir",
                    str(smm),
                ],
                capture_output=True,
                text=True,
                env=_bf.GIT_ENV,
            )
            # Advisory printed AND the merge proceeded (exit 0, source merged).
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("1/2", result.stdout)
            self.assertIn("deadbee", result.stdout)
            self.assertFalse(_bf.branch_exists(repo_td, "feature-x"))


class TestCmdMergeFailOpen(unittest.TestCase):
    """The post-merge accounting (merge-commit event + trailer advisory) is
    fail-open: a failure AFTER the --no-ff merge commits but BEFORE push/delete
    must NEVER change cmd_merge's exit code. The realistic trigger is
    LockTimeoutError (a plain Exception, not OSError/ValueError) raised by the
    locked event read under parallel-teammate flock contention — exactly the
    scenario this branch runs. A regression would leave the source
    merged-but-unpushed and force a manual cleanup.
    """

    def _run_in_process_merge(self, raise_in: str) -> int:
        import argparse
        from unittest import mock

        import close_common
        from _append_impl import LockTimeoutError

        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as repo_td,
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as smm_td,
        ):
            _bf.init_repo(repo_td)
            main = _bf.get_current_branch(repo_td)
            _bf.make_commit(repo_td, "feature-x", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=repo_td, capture_output=True, check=True
            )
            _write_events(Path(smm_td), [open_concern_event()])

            args = argparse.Namespace(
                cwd=repo_td,
                source="feature-x",
                target=main,
                smm_dir=smm_td,
                verify_gate=None,
            )

            def boom(*_a, **_k):
                raise LockTimeoutError("events.jsonl lock held by a teammate")

            patches = {
                "merge_event": mock.patch.object(
                    close_common, "append_merge_commit_event", side_effect=boom
                ),
                "advisory": mock.patch.object(
                    close_common.trailer_gate, "advisory", side_effect=boom
                ),
            }
            with patches[raise_in]:
                rc = close_common.cmd_merge(args)
            # Either way the merge must have completed and the source deleted.
            self.assertFalse(_bf.branch_exists(repo_td, "feature-x"))
            return rc

    def test_merge_commit_event_lock_timeout_does_not_abort(self):
        self.assertEqual(self._run_in_process_merge("merge_event"), 0)

    def test_trailer_advisory_lock_timeout_does_not_abort(self):
        self.assertEqual(self._run_in_process_merge("advisory"), 0)


class TestAdvisoryPreReadIndependence(_AssertNotNoneMixin, unittest.TestCase):
    """advisory(smm_dir) with NO pre-read params reads its OWN events/sprint
    (the independence guarantee), and passing a pre-read snapshot yields
    byte-for-byte the same output as the self-read baseline."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.smm = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

    def _seed_sub_threshold(self) -> None:
        _write_events(
            self.smm,
            [
                open_concern_event(),
                _code_commit(["aaa"], "2026-04-05T10:00:00+00:00", "h1", "did link"),
                _code_commit(["bbb"], "2026-04-05T11:00:00+00:00", "h2", "also link"),
                _code_commit([], "2026-04-05T12:00:00+00:00", "deadbee", "no trailer"),
            ],
        )

    def test_no_params_reads_own_events(self):
        # Independence: standalone advisory(smm_dir) must still acquire its own
        # locked read — exactly one call, no pre-read handed in.
        from unittest import mock

        import _common
        import trailer_gate

        self._seed_sub_threshold()
        real = _common.read_events_locked
        slugs: list[str] = []

        def spy(smm_dir, slug):
            slugs.append(slug)
            return real(smm_dir, slug)

        with mock.patch.object(_common, "read_events_locked", side_effect=spy):
            msg = self._assert_not_none(trailer_gate.advisory(self.smm))
        self.assertEqual(len(slugs), 1, f"standalone advisory self-reads once: {slugs}")
        self.assertIn("2/3", msg)

    def test_passed_events_skips_own_read(self):
        # When a pre-read is handed in, the advisory must NOT re-read events.
        from unittest import mock

        import _common
        import sprint_store
        import trailer_gate

        self._seed_sub_threshold()
        events = _common.read_events_locked(self.smm, "seed")
        sprint = sprint_store.load_sprint(self.smm)
        with mock.patch.object(
            _common, "read_events_locked", side_effect=AssertionError("re-read!")
        ):
            msg = self._assert_not_none(
                trailer_gate.advisory(self.smm, events=events, sprint=sprint)
            )
        self.assertIn("2/3", msg)

    def test_pre_read_output_matches_self_read_baseline(self):
        # Byte-for-byte: the shared-read advisory equals the double-read baseline.
        import _common
        import sprint_store
        import trailer_gate

        self._seed_sub_threshold()
        baseline = self._assert_not_none(trailer_gate.advisory(self.smm))
        events = _common.read_events_locked(self.smm, "seed")
        sprint = sprint_store.load_sprint(self.smm)
        shared = self._assert_not_none(
            trailer_gate.advisory(self.smm, events=events, sprint=sprint)
        )
        self.assertEqual(baseline, shared)


class TestCmdMergeSingleRead(unittest.TestCase):
    """cmd_merge takes ONE locked events read and shares it with both post-merge
    consumers (merge-event append + trailer advisory), closing debt
    c75e3e2d1742 — the prior double read/double load."""

    def test_cmd_merge_reads_events_exactly_once(self):
        import argparse
        from unittest import mock

        import _common
        import close_common

        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as repo_td,
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as smm_td,
        ):
            _bf.init_repo(repo_td)
            main = _bf.get_current_branch(repo_td)
            _bf.make_commit(repo_td, "feature-x", "f.txt", "x", "feature commit")
            subprocess.run(
                ["git", "checkout", main], cwd=repo_td, capture_output=True, check=True
            )
            smm = Path(smm_td)
            _write_events(
                smm,
                [
                    open_concern_event(),
                    _code_commit(
                        ["aaa"], "2026-04-05T10:00:00+00:00", "hash111", "did link"
                    ),
                    _code_commit(
                        [], "2026-04-05T11:00:00+00:00", "deadbee", "forgot trailer"
                    ),
                ],
            )

            args = argparse.Namespace(
                cwd=repo_td,
                source="feature-x",
                target=main,
                smm_dir=smm_td,
                verify_gate=None,
                force_verify=False,
            )

            real = _common.read_events_locked
            slugs: list[str] = []

            def spy(smm_dir, slug):
                slugs.append(slug)
                return real(smm_dir, slug)

            with mock.patch.object(_common, "read_events_locked", side_effect=spy):
                rc = close_common.cmd_merge(args)

            self.assertEqual(rc, 0)
            self.assertEqual(
                len(slugs), 1, f"expected ONE locked events read, got {slugs}"
            )


class TestCloseCommonLineCap(unittest.TestCase):
    """The extraction must land close_common.py back under the 500-line cap."""

    def test_close_common_at_or_under_500_lines(self):
        path = _PLUGIN_ROOT / "scripts" / "close_common.py"
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(
            line_count,
            500,
            f"close_common.py is {line_count} lines — extract more to stay "
            f"under the 500-line cap",
        )


class TestThresholdSync(unittest.TestCase):
    """The 0.80 trailer target has one canonical home (retro_metrics) shared by
    the pre-merge advisory and the retro Fix trigger — they must never drift."""

    def test_trailer_gate_threshold_is_the_canonical_target(self):
        import retro_metrics
        import trailer_gate

        self.assertEqual(
            trailer_gate.THRESHOLD, retro_metrics.RESOLVES_LINK_RATE_TARGET
        )

    def test_retro_agent_prose_matches_the_canonical_target(self):
        # The retro agent applies the same threshold as LLM prose (it cannot
        # import the constant). Pin the value so prose can't silently drift from
        # retro_metrics.RESOLVES_LINK_RATE_TARGET.
        import retro_metrics

        agent_md = _PLUGIN_ROOT / "agents" / "xp-retrospective.md"
        text = agent_md.read_text(encoding="utf-8")
        target_str = f"{retro_metrics.RESOLVES_LINK_RATE_TARGET:.2f}"
        self.assertIn(
            f"Below {target_str}",
            text,
            "xp-retrospective.md must flag resolves_link_rate below the "
            f"canonical target {target_str} as a Fix",
        )


if __name__ == "__main__":
    unittest.main()
