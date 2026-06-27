#!/usr/bin/env python3
"""Unit tests for the xp-quality-review risk_classifier (story-002).

Project-agnostic content-heuristic classifier: scores each changed file on
generic CS risk signals (state-field density, exit/decision blocks, lock/async
primitives, lifecycle method pairs, async complexity), then emits
RISK=high|low + a SIGNALS= line naming the contributing files+matched
signals.

Why content-shape, not file-path patterns: the plugin ships to many projects;
classifying on this repo's own gate/marker paths would not transfer. See
system_context.json principle 'plugin-project-agnostic' (added with this
story) and SMM constraint 2dac3b6c2098.
"""

import io
import sys
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-quality-review" / "scripts"
    ),
)

import risk_classifier

_HIGH_STATE_SRC = textwrap.dedent("""
    class Cycle:
        def __init__(self):
            self.a = 1
            self.b = 2
            self.c = 3
            self.d = 4
            self.e = 5
        def reset(self):
            self.a = 0
            self.b = 0
""").strip()

_EXIT_SRC = textwrap.dedent("""
    import sys
    def gate(ok: bool) -> None:
        if not ok:
            sys.exit(2)
        print("ok")
""").strip()

_LOCK_SRC = textwrap.dedent("""
    import threading
    LOCK = threading.Lock()
    def critical():
        with LOCK:
            pass
""").strip()

_CONTEXT_MGR_SRC = textwrap.dedent("""
    class Resource:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
""").strip()

_START_STOP_SRC = textwrap.dedent("""
    class Server:
        def start(self):
            pass
        def stop(self):
            pass
""").strip()

_ASYNC_SRC = textwrap.dedent("""
    import asyncio
    async def fan_out():
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.gather()
""").strip()

_PURE_DATA_SRC = textwrap.dedent('''
    """Pure constants module."""
    NAME = "x"
    VERSION = "1.0"
    PI = 3.14
    GREETING = "hello"
''').strip()


class TestRiskClassifierAPI(unittest.TestCase):
    """Public API: classify(file_paths, repo_root) -> {'risk', 'signals'}."""

    def setUp(self):
        self.tmpdir = Path(self._tempdir())

    def _tempdir(self) -> str:
        import tempfile

        d = tempfile.mkdtemp(prefix="risk_classifier_test_")
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d

    def _write(self, name: str, src: str) -> str:
        p = self.tmpdir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src)
        return str(p.relative_to(self.tmpdir))

    def _classify(self, *files: str) -> dict:
        return risk_classifier.classify(list(files), repo_root=self.tmpdir)

    # --- low-risk cases ---

    def test_empty_file_list_low(self):
        self.assertEqual(self._classify()["risk"], "low")

    def test_empty_file_low(self):
        f = self._write("empty.py", "")
        self.assertEqual(self._classify(f)["risk"], "low")

    def test_pure_data_module_low(self):
        f = self._write("data.py", _PURE_DATA_SRC)
        self.assertEqual(self._classify(f)["risk"], "low")

    def test_non_python_extension_low(self):
        # .sh/.md fall outside v1 scope; treated as low (no parse).
        md = self._write("doc.md", "# heading\n" + _EXIT_SRC)
        sh = self._write("hook.sh", "#!/bin/bash\nexit 2\n")
        self.assertEqual(self._classify(md, sh)["risk"], "low")

    def test_missing_file_silently_skipped(self):
        # Reference a non-existent path; classifier must not crash, returns low.
        self.assertEqual(self._classify("does/not/exist.py")["risk"], "low")

    # --- high-risk single-signal cases ---

    def test_high_state_field_density_high(self):
        f = self._write("cycle.py", _HIGH_STATE_SRC)
        result = self._classify(f)
        self.assertEqual(result["risk"], "high")
        matched = next(s["matched"] for s in result["signals"] if s["file"] == f)
        self.assertIn("state-field-density", matched)

    def test_exit_decision_high(self):
        f = self._write("gate.py", _EXIT_SRC + "\n" + _PURE_DATA_SRC)
        result = self._classify(f)
        self.assertEqual(result["risk"], "high")
        matched = next(s["matched"] for s in result["signals"] if s["file"] == f)
        self.assertIn("exit-decision", matched)

    def test_lock_primitive_high(self):
        # Lock + exit together exercise the multi-signal aggregation path;
        # the test asserts on lock-primitives specifically.
        f = self._write(
            "guarded.py",
            _LOCK_SRC + "\n" + _EXIT_SRC,
        )
        result = self._classify(f)
        self.assertEqual(result["risk"], "high")
        matched = next(s["matched"] for s in result["signals"] if s["file"] == f)
        self.assertIn("lock-primitives", matched)

    def test_lifecycle_context_manager_high(self):
        f = self._write(
            "res.py",
            _CONTEXT_MGR_SRC + "\n" + _EXIT_SRC,
        )
        result = self._classify(f)
        self.assertEqual(result["risk"], "high")
        matched = next(s["matched"] for s in result["signals"] if s["file"] == f)
        self.assertIn("lifecycle-methods", matched)

    def test_lifecycle_start_stop_high(self):
        f = self._write(
            "srv.py",
            _START_STOP_SRC + "\n" + _EXIT_SRC,
        )
        result = self._classify(f)
        self.assertEqual(result["risk"], "high")
        matched = next(s["matched"] for s in result["signals"] if s["file"] == f)
        self.assertIn("lifecycle-methods", matched)

    def test_async_complexity_high(self):
        f = self._write(
            "io.py",
            _ASYNC_SRC + "\n" + _EXIT_SRC,
        )
        result = self._classify(f)
        self.assertEqual(result["risk"], "high")
        matched = next(s["matched"] for s in result["signals"] if s["file"] == f)
        self.assertIn("async-complexity", matched)

    # --- regex edge cases (self-assign discriminator) ---

    def test_self_eq_comparison_does_not_count_as_state_write(self):
        """`self.X == Y` is a boolean comparison, NOT a state write.

        Without the trailing `(?!=)` guard the bare `=` regex matches the
        first `=` of `==`, inflating state-field-density and tripping RISK=high
        on conditional-heavy code that mutates nothing.
        """
        src = textwrap.dedent("""
            def check(self):
                self.foo == 1
                self.bar == 2
                self.baz == 3
                self.qux == 4
        """).strip()
        f = self._write("compare_only.py", src)
        self.assertEqual(self._classify(f)["risk"], "low")

    def test_augmented_assignment_counts_as_state_write(self):
        """`self.X += ...` (and `-=`, `*=`, `//=`, ...) is a state mutation.

        The bare `=` regex would miss these. A counter/flag class that mutates
        purely via augmented ops is exactly the state-machine shape this signal
        exists to catch.
        """
        src = textwrap.dedent("""
            class Counter:
                def tick(self):
                    self.count += 1
                    self.errors -= 1
                    self.total *= 2
                    self.rate //= 3
        """).strip()
        f = self._write("counter.py", src)
        result = self._classify(f)
        self.assertEqual(result["risk"], "high")
        matched = next(s["matched"] for s in result["signals"] if s["file"] == f)
        self.assertIn("state-field-density", matched)

    # --- mixed / multi-file ---

    def test_mixed_signals_multifile_names_each(self):
        f1 = self._write("a.py", _LOCK_SRC + "\n" + _EXIT_SRC)
        f2 = self._write("b.py", _HIGH_STATE_SRC)
        f3 = self._write("c.py", _PURE_DATA_SRC)
        result = self._classify(f1, f2, f3)
        self.assertEqual(result["risk"], "high")
        contributors = {s["file"] for s in result["signals"]}
        self.assertIn(f1, contributors)
        self.assertIn(f2, contributors)
        self.assertNotIn(f3, contributors)

    # --- convenience fixture (AC-4 "fixture, not rule" branch) ---

    def test_convenience_fixture_real_plugin_file_high(self):
        """A file from THIS repo with state/exit semantics classifies high.

        Validates AC-4: the xp-agents repo provides convenient fixtures
        because its own scripts are state-machine-shaped, NOT because the
        classifier hardcodes its paths. Any project whose code has the same
        content shape gets the same classification.
        """
        repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        candidate = (
            repo_root / "plugins" / "xp-agents" / "scripts" / "review_cycle_done.py"
        )
        if not candidate.exists():
            self.skipTest(f"convenience fixture missing: {candidate}")
        rel = str(candidate.relative_to(repo_root))
        result = risk_classifier.classify([rel], repo_root=repo_root)
        self.assertEqual(result["risk"], "high", f"signals: {result['signals']}")


class TestRiskClassifierCLI(unittest.TestCase):
    """CLI shape: prints RISK=high|low + SIGNALS=<...> to stdout, exit 0."""

    def setUp(self):
        import shutil
        import tempfile

        self.tmpdir = Path(tempfile.mkdtemp(prefix="risk_classifier_cli_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def _write(self, name: str, src: str) -> Path:
        p = self.tmpdir / name
        p.write_text(src)
        return p

    def _run(self, *files: str) -> str:
        argv = ["risk_classifier", *files]
        buf = io.StringIO()
        with patch.object(sys, "argv", argv), redirect_stdout(buf):
            risk_classifier.main()
        return buf.getvalue()

    def test_no_files_emits_low_and_empty_signals(self):
        out = self._run()
        self.assertIn("RISK=low", out)
        self.assertIn("SIGNALS=", out)

    def test_high_risk_emits_high_and_names_file(self):
        f = self._write("gated.py", _LOCK_SRC + "\n" + _EXIT_SRC)
        out = self._run(str(f))
        self.assertIn("RISK=high", out)
        self.assertIn("gated.py", out)

    def test_low_risk_emits_low(self):
        f = self._write("data.py", _PURE_DATA_SRC)
        out = self._run(str(f))
        self.assertIn("RISK=low", out)


if __name__ == "__main__":
    unittest.main()
