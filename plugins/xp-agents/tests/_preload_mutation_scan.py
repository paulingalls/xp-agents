#!/usr/bin/env python3
"""Where a preload mutates state by running — derived, never hand-listed.

Split out of `tests/skills/test_preload_side_effects.py` at the 500-line cap:
that module is the REGISTRY (what a refusal does to each site, and why) and
this one is the SCAN that produces the population it must cover. Keeping them
apart is also the honest shape — the scan is the thing whose blind spots need
stating, and the registry is the thing a reviewer reads.

A VERB scan over shell text: the verbs below, on non-comment lines, across every
preload entry point (`skills/*/scripts/*.sh`) and the shared library they source
(`skills/_preload_*.sh` — sourced code is preload code, and six sites live
there). It does NOT understand the Python those scripts shell out to, so a
preload that mutates state through a `python3 .../some_cli.py write` subcommand
is invisible here unless its FLAG is named below. Two are, because that hole was
otherwise load-bearing, and both are `close_cycle_abandonment.py`:
`--arm-only` is the close preloads' PRIMARY close-cycle arming (the
`write_marker CLOSE_CYCLE_ACTIVE` beside it is only its fallback), and
`--detector` both appends a high-severity concern and consumes that same
marker. Read the hole as open for every other subcommand: the flags here were
added because a real site needed them, not because the set is closed.
"""

import re
from dataclasses import dataclass
from pathlib import Path

# Verbs that take a target as their next token. The target is what makes two
# sites in one script separately classifiable — `xp-review-plan` deletes both a
# gate and a pointer with `rm -f`, and only one of them matters on a refusal.
#
# `--detector` is a FLAG rather than a shell helper, and it sits here rather than
# in `_FLAG_VERB` below for the same reason: the detector name is the target, and
# a preload gaining a second detector must classify it separately.
_TARGET_VERBS: tuple[str, ...] = (
    "consume_marker",
    "write_marker",
    "emit_close_started_event",
    "--detector",
)

# `rm -f` is spelled with a space, so it needs its own pattern rather than a
# place in the tuple above.
_RM_F = re.compile(r"(?<![\w-])rm\s+-f(?![\w-])(\s+(?P<target>\S+))?")

# Flags whose PRESENCE is the mutation: the flag is the verb and there is no
# separate target. `--arm-only` is the only one with a site today; `--consume`
# had one (`xp-assign`'s `--consume-gate`, retired in story-021) and stays in the
# alternation because this is a SCAN, whose job is to name a site that does not
# exist yet — unlike the registry beside it, where an entry matching no site is
# the defect. Read a green run as "no `--consume-*` flag was added", not as
# coverage of one.
_FLAG_VERB = re.compile(r"--(?:consume|arm-only)[\w-]*")

# A shell redirect writing INTO the SMM dir. Not a helper call, so no other
# pattern here sees it, and one shipped site depends on it.
_SMM_REDIRECT = re.compile(r">\s*\"?(?P<target>\$\{?SMM_DIR\}?[^\"'\s]*)")

# `append.sh` writes the event log. Bare verb — the arguments are on
# continuation lines, so there is no target token to read.
_APPEND = re.compile(r"(?<![\w-])append\.sh(?![\w-])")

# A shell function DEFINITION of one of the verbs above is not a call site, but
# it is not noise either: it is where the mutation is implemented, and dropping
# it silently would make the population smaller than it looks.
_DEFINITION_TARGET = "(definition)"


@dataclass(frozen=True, order=True)
class Site:
    """One mutation site, keyed so a rewrite of the line forces reclassification.

    `script` is relative to `skills/`; `target` is the marker name, path or mode
    the verb acts on, `""` for a bare verb. Deliberately NOT keyed on the line
    number: renumbering a script is not a change in what it mutates, and a key
    that churned on every edit above it would train readers to re-stamp the
    registry without reading it.
    """

    script: str
    verb: str
    target: str


def _dequote(token: str) -> str:
    return token.strip("\"'")


def _sites_in_line(line: str) -> set[tuple[str, str]]:
    """The (verb, target) pairs this one line of shell declares."""
    found: set[tuple[str, str]] = set()

    for verb in _TARGET_VERBS:
        for match in re.finditer(rf"(?<![\w.-]){re.escape(verb)}(?![\w-])", line):
            rest = line[match.end() :]
            if rest.lstrip().startswith("()"):
                found.add((verb, _DEFINITION_TARGET))
                continue
            tokens = rest.split()
            found.add((verb, _dequote(tokens[0]) if tokens else ""))

    for match in _RM_F.finditer(line):
        target = match.group("target")
        found.add(("rm -f", _dequote(target) if target else ""))

    for match in _FLAG_VERB.finditer(line):
        found.add((match.group(0), ""))

    for match in _SMM_REDIRECT.finditer(line):
        found.add((">SMM_DIR", _dequote(match.group("target"))))

    if _APPEND.search(line):
        found.add(("append.sh", ""))

    return found


def _preload_sources(skills_dir: Path) -> list[Path]:
    """Every shell file a preload run executes: the entry points and the
    library they source. Sorted so a failure message reads in a stable order."""
    return sorted(
        [*skills_dir.glob("*/scripts/*.sh"), *skills_dir.glob("_preload_*.sh")]
    )


def scan_mutation_sites(skills_dir: Path) -> set[Site]:
    """Every mutation site in the preload surface under `skills_dir`."""
    sites: set[Site] = set()
    for script in _preload_sources(skills_dir):
        relative = script.relative_to(skills_dir).as_posix()
        for line in script.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            for verb, target in _sites_in_line(line):
                sites.add(Site(relative, verb, target))
    return sites
