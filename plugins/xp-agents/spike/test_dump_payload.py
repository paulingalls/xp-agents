#!/usr/bin/env python3
"""Throwaway: pins the spike recorder's ONE load-bearing contract.

Verbatim capture is the only thing this recorder must get right, and no other
check in story-001 distinguishes a faithful recorder from a normalising or
silently-truncating one. A swallowed or reshaped payload reads downstream as
"this event never fired" and would reach the go/no-go verdict as a false
negative, so the contract gets a real red/green test.

Deleted with the rest of the rig before story close. Run explicitly:
    pytest plugins/xp-agents/spike/test_dump_payload.py
(`pytest.ini` sets `testpaths` to the tests dir, so the default run skips it.)
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_RECORDER = Path(__file__).parent / "_dump_payload.py"

# Deliberately hostile: non-ASCII, embedded quotes and backslashes, an embedded
# newline, CRLF, a trailing space, and duplicate-ish key ordering. A recorder
# that json.loads/json.dumps round-trips will reorder or re-escape and fail.
_AWKWARD = (
    '{"hook_event_name":"PreToolUse","b":1,"a":2,'
    '"quote":"he said \\"hi\\"","back":"C:\\\\tmp",'
    '"nl":"line1\\nline2","crlf":"x\\r\\ny","unicode":"café — 日本語 🎉",'
    '"trailing":"space "} '
)


class TestRecorderCapturesVerbatim(unittest.TestCase):
    def _run(self, payload: str, outdir: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_RECORDER)],
            input=payload.encode("utf-8"),
            capture_output=True,
            env={"XP_SPIKE_DIR": str(outdir), "PATH": "/usr/bin:/bin"},
        )

    def test_payload_file_is_byte_identical_to_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            self._run(_AWKWARD, outdir)

            raws = sorted((outdir / "payloads").glob("*.raw"))
            self.assertEqual(len(raws), 1, f"expected one payload file, got {raws}")
            self.assertEqual(
                raws[0].read_bytes(),
                _AWKWARD.encode("utf-8"),
                "recorder must write stdin VERBATIM — no reformatting, "
                "re-escaping, key reordering, or whitespace trimming",
            )

    def test_never_writes_stdout_and_always_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            r = self._run(_AWKWARD, Path(td))
            self.assertEqual(r.returncode, 0)
            self.assertEqual(
                r.stdout, b"", "stdout would inject context into the host's turn"
            )

    def test_unparseable_stdin_is_still_captured_verbatim(self) -> None:
        garbage = "not json at all \x00\x01 <<<"
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            r = self._run(garbage, outdir)
            self.assertEqual(r.returncode, 0)
            raws = sorted((outdir / "payloads").glob("*.raw"))
            self.assertEqual(len(raws), 1)
            self.assertEqual(raws[0].read_bytes(), garbage.encode("utf-8"))

    def test_index_records_event_name_and_byte_count(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            self._run(_AWKWARD, outdir)
            lines = (outdir / "index.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["hook_event_name"], "PreToolUse")
            self.assertEqual(entry["stdin_bytes"], len(_AWKWARD.encode("utf-8")))
            self.assertIn("payload_file", entry)

    def test_two_firings_do_not_overwrite_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            self._run('{"hook_event_name":"Stop"}', outdir)
            self._run('{"hook_event_name":"Stop"}', outdir)
            self.assertEqual(len(sorted((outdir / "payloads").glob("*.raw"))), 2)


if __name__ == "__main__":
    unittest.main()
