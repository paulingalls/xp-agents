#!/usr/bin/env python3
"""PostToolUseFailure command hook for Bash: capture failed test runs.

PostToolUse only fires on success; when a Bash command exits non-zero,
PostToolUseFailure fires instead. That is EVERY failing Bash command, not just
a failing test run — which is the whole difficulty here. `is_test_run` matches
a runner name anywhere in the command, so without attribution this hook blames
the runner for exit codes it never produced: a compound command short-circuiting
before the runner (`validator && pytest`), or a `grep -rn pytest src/` exiting 1
on no-match. The TDD gates then read that concern as "tests are failing" for a
session in which no test ever ran.

`test_attribution` decides whether the runner is honestly to blame. When it is,
we record a test-failure concern exactly as before — a real failing run must
still gate. When it is not, we record only a STATUS: the command failed, and we
make no claim about tests. A concern there would be unresolvable (no later test
run clears it) and would gate the session forever.

Note this hook does NOT own every failing test run — the parsed-counts path in
`bash_post_tool` sees the ones that exit non-zero with a readable summary, and
it always has. This hook is the fallback for failures with no parseable output.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import append_validation
import concerns
import identity
import test_attribution
from event_schema import STATUS_ACTION_BASH_FAILED, get_required_budget
from test_parsing import is_test_run

# The `error` payload leads with the harness's own "Exit code N" line. Taking
# line 1 verbatim made every concern read "Test command failed (pytest): Exit
# code 1" — diagnostically worthless, and the code is already in metadata.
_EXIT_CODE_LINE_RE = re.compile(r"^Exit code \d+$", re.IGNORECASE)


def _first_meaningful_line(error: str) -> str:
    """The first line of `error` that says something the exit code doesn't."""
    for line in error.splitlines():
        line = line.strip()
        if line and not _EXIT_CODE_LINE_RE.match(line):
            return line
    return "exit non-zero"


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Record failed test runs in the SMM."""
    if _common.is_xp_agent(input_data):
        return None

    # Skip user interrupts — not a real failure
    if input_data.get("is_interrupt"):
        return None

    # Cheap reject before any I/O: a command that names no runner at all is
    # somebody else's failure entirely.
    command = input_data.get("tool_input", {}).get("command", "")
    if not is_test_run(command):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = identity.resolve_agent_id(input_data)
    try:
        append_validation.validate_agent_id(agent_id)
    except ValueError:
        return None
    error = input_data.get("error", "")

    framework = test_attribution.attribute_failure(command, error)

    # M2 dual-emit: metadata.action + exit_code (when the hook input provides
    # one) are the canonical signal; content stays a human-readable digest.
    if framework:
        prefix = f"Test run failed ({framework}): "
    else:
        prefix = "Command failed — no observed test run (ambiguous): "
    budget = get_required_budget(_common.STATUS)
    metadata: dict = {"action": STATUS_ACTION_BASH_FAILED}
    exit_code = input_data.get("exit_code")
    if exit_code is not None:
        metadata["exit_code"] = exit_code
    status = _common.make_event(
        _common.STATUS,
        agent_id,
        f"{prefix}{error[: budget - len(prefix)]}",
        working_on=[],
        metadata=metadata,
    )
    _common.append_safe(smm_dir, status)

    if not framework:
        return None

    # Concise concern — the agent already saw the full error in the tool
    # response. When the payload corroborated the failure with real counts,
    # report those instead of a bare exit.
    failed = test_attribution.parsed_failed_count(error, framework)
    if failed is not None:
        content = f"{concerns.TEST_FAILURES_PREFIX}: {failed} failed ({framework})"
    else:
        # The detail line is real runner output and has no length bound (a
        # one-line stack trace, a long assert repr). `append_safe` SILENTLY
        # DROPS an event that busts its content budget, so an unbounded detail
        # loses the concern and the gate goes quiet on a genuinely failing run
        # — the worst direction. Bound it to what the budget can hold.
        head = f"{concerns.TEST_COMMAND_FAILED_PREFIX} ({framework}): "
        detail = _common.truncate(
            _first_meaningful_line(error),
            get_required_budget(_common.CONCERN) - len(head),
        )
        content = f"{head}{detail}"
    concern = _common.make_event(
        _common.CONCERN,
        agent_id,
        content,
        severity="high",
    )
    _common.append_safe(smm_dir, concern)

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
