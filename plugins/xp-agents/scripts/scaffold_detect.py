#!/usr/bin/env python3
"""Detection helpers for /xp-scaffold-acceptance.

Three pure-read functions consumed by the scaffold-acceptance skill:

- read_acceptance_surfaces(smm_dir): pull the acceptance_surfaces array from
  system_context.json (empty list when absent).
- canonical_tools_for(surface): static map mirroring the
  xp-system-analyzer surface table.
- detect_existing_tooling(surface, repo_root): look for known config files of
  any canonical tool for the surface; first hit wins.

No writes, no installs, no shell-outs. Skill orchestration lives in SKILL.md.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _probe import probe_config_file
from system_context_store import load_system_context

_CANONICAL_TOOLS: dict[str, list[str]] = {
    "http_websocket": [
        "supertest",
        "httpx",
        "k6",
        "hurl",
        "bruno",
        "dredd",
        "pact",
        "grpcurl",
        "postman",
        "newman",
    ],
    "browser": [
        "playwright",
        "cypress",
        "puppeteer",
        "selenium",
        "webdriverio",
        "testcafe",
        "nightwatch",
    ],
    "cli": [
        "bats",
        "aruba",
        "cram",
        "pytest-console-scripts",
    ],
    "sdk": [
        "doctest",
        "hypothesis",
        "fast-check",
    ],
    "automation": [
        "detox",
        "maestro",
        "appium",
        "xcuitest",
        "selenium",
        "webdriverio",
        "taiko",
        "espresso",
        "earl-grey",
        "calabash",
    ],
    "message_event": [
        "testcontainers",
        "localstack",
        "wiremock",
        "mockserver",
        "pact",
    ],
}

# Per-tool config detection. Tuple is (filename, marker): when marker is None,
# file existence alone signals presence; otherwise the marker substring must
# appear in the file (used for shared containers like pyproject.toml).
_TOOL_CONFIGS: dict[str, list[tuple[str, str | None]]] = {
    "playwright": [
        ("playwright.config.ts", None),
        ("playwright.config.js", None),
        ("playwright.config.mjs", None),
    ],
    "cypress": [
        ("cypress.config.ts", None),
        ("cypress.config.js", None),
        ("cypress.config.mjs", None),
        ("cypress.json", None),
    ],
    "hurl": [("hurl.config", None)],
    "bruno": [("bruno.json", None)],
    "bats": [(".batsrc", None)],
    "pytest-console-scripts": [
        ("pytest.ini", None),
        ("pyproject.toml", "[tool.pytest.ini_options]"),
    ],
    "detox": [(".detoxrc.json", None), (".detoxrc.js", None)],
    "appium": [("appium.conf.json", None), ("appium.config.json", None)],
}

# Surfaces whose canonical tools generally lack a single config-file signal
# (sdk: doctest/hypothesis are inline; message_event: testcontainers et al.
# wire in via test-runner code). detect_existing_tooling will return
# has_tooling=False for these — the skill must not interpret that as proof
# of absence; it's "no config-file signal."
NO_CONFIG_FILE_SIGNAL: frozenset[str] = frozenset({"sdk", "message_event"})


def read_acceptance_surfaces(smm_dir: Path) -> list[dict]:
    """Return the acceptance_surfaces array from system_context.json.

    Returns [] when the file is missing or the field is absent. Propagates
    ValueError (corrupt or schema-invalid file) and OSError (symlink attack)
    from load_system_context — corruption and security signals must not be
    silently swallowed.
    """
    doc = load_system_context(smm_dir)
    if not doc:
        return []
    surfaces = doc.get("acceptance_surfaces", [])
    return surfaces if isinstance(surfaces, list) else []


def canonical_tools_for(surface_name: str) -> list[str]:
    """Return the canonical tool list for a surface, or [] if unknown."""
    return list(_CANONICAL_TOOLS.get(surface_name, []))


def detect_existing_tooling(surface_name: str, repo_root: Path) -> dict:
    """Detect whether any canonical tool for the surface is configured.

    Walks the canonical tool list in order; the first tool with a matching
    config file wins. Returns {has_tooling, tool_name, config_files}.

    Note: surfaces in NO_CONFIG_FILE_SIGNAL (sdk, message_event) have no
    reliable single-file config marker. has_tooling=False for those
    surfaces means "no config-file signal," not "no tooling exists" —
    the caller must not scaffold over them on that signal alone.
    """
    for tool in canonical_tools_for(surface_name):
        hits = [
            match
            for filename, marker in _TOOL_CONFIGS.get(tool, [])
            if (match := probe_config_file(repo_root, filename, marker)) is not None
        ]
        if hits:
            return {
                "has_tooling": True,
                "tool_name": tool,
                "config_files": hits,
            }
    return {"has_tooling": False, "tool_name": None, "config_files": []}


def find_introducing_commit(repo_root: Path, config_files: list[Path]) -> dict | None:
    """Return metadata for the OLDEST commit that introduced any of the given files.

    For each path in ``config_files``, runs
    ``git log --diff-filter=A --follow --format=<sep> -- <file>`` to find the
    add-only commits and picks the latest line (oldest, since git log walks newest-
    first). Across all files, the OLDEST result wins — that is the canonical
    "scaffold introduction" commit the re-invocation redo branch points the user at.

    Returns ``{"sha": str, "subject": str, "date": str (ISO 8601 with offset)}``
    or ``None`` when no config file has a tracked introducer (untracked, missing,
    not-a-git-repo, or git unavailable). Does not raise on git failures —
    returns None and lets the caller decide how to proceed.
    """
    sep = "\x1f"
    # %ct (committer timestamp, seconds since epoch) is the sort key —
    # robust across timezone boundaries; %ci is the human-readable date
    # we surface to callers.
    fmt = f"%H{sep}%s{sep}%ci{sep}%ct"
    candidates: list[tuple[str, str, str, int]] = []
    for path in config_files:
        try:
            r = subprocess.run(
                [
                    "git",
                    "log",
                    "--diff-filter=A",
                    "--follow",
                    f"--format={fmt}",
                    "--",
                    str(path),
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode != 0:
            return None
        lines = [line for line in r.stdout.splitlines() if line.strip()]
        if not lines:
            continue
        # `git log` walks newest-first; --diff-filter=A gives only add commits;
        # with --follow, the LAST line is the original introducer (earliest
        # ancestor across renames).
        sha, subject, date, ts = lines[-1].split(sep, 3)
        candidates.append((sha, subject, date, int(ts)))
    if not candidates:
        return None
    sha, subject, date, _ = min(candidates, key=lambda c: c[3])
    return {"sha": sha, "subject": subject, "date": date}
