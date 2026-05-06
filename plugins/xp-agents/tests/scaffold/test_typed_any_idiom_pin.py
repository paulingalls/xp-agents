#!/usr/bin/env python3
"""Doctrinal pin: forbid `# type: ignore[no-untyped-def]` in scaffold tests.

Sprint-064 story-007 converted `fake_write` to the typed-Any idiom
(`def fake_write(path: Path, content: str, **kw: Any) -> None`); story-012
finished the sweep for `fake_copy`. This pin catches a regression where a
future test double under `tests/scaffold/` re-introduces the untyped form
with a blanket `# type: ignore[no-untyped-def]` instead of typing the
signature.

Grep-based by design: the failure mode is a literal substring, and the
production rule is "this string must not appear in this directory."
"""

import unittest
from pathlib import Path

SCAFFOLD_TESTS = Path(__file__).parent  # plugins/xp-agents/tests/scaffold/
THIS_FILE = Path(__file__).resolve()
FORBIDDEN = "# type: ignore[no-untyped-def]"


class TestTypedAnyIdiomPin(unittest.TestCase):
    def test_no_no_untyped_def_ignores_in_scaffold_tests(self) -> None:
        offenders: list[str] = []
        for py_file in sorted(SCAFFOLD_TESTS.rglob("*.py")):
            if py_file.resolve() == THIS_FILE:
                continue  # the pin file itself names the literal
            for lineno, line in enumerate(
                py_file.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if FORBIDDEN in line:
                    offenders.append(f"  {py_file.name}:{lineno}: {line.strip()}")
        if offenders:
            self.fail(
                f"{len(offenders)} `{FORBIDDEN}` occurrence(s) in "
                f"tests/scaffold/ — convert the test double to the "
                f"typed-Any idiom (e.g. `**kw: Any`):\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
