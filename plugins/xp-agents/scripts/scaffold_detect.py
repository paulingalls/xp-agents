#!/usr/bin/env python3
"""Detection helpers for /xp-scaffold-acceptance.

Pure-read functions consumed by the scaffold-acceptance skill:

- read_acceptance_surfaces(smm_dir): pull the acceptance_surfaces array from
  system_context.json (empty list when absent).
- canonical_tools_for(surface): static map mirroring the
  xp-system-analyzer surface table.
- detect_existing_tooling(surface, repo_root): look for known config files of
  any canonical tool for the surface; first hit wins.
- find_introducing_commit(repo_root, config_files): git-log lookup of the
  oldest commit that introduced any of the config files. Best-effort —
  shells out to ``git log`` and returns None on any failure.
- detect_monorepo(repo_root): pure-read priority-ordered monorepo signal
  detection across pnpm/turbo/nx/lerna/workspaces/cargo/multi-pyproject.

No writes, no installs. ``find_introducing_commit`` shells out to ``git
log`` (argv-only, no shell, best-effort None-on-failure); other helpers
are pure file/JSON/TOML reads. Skill orchestration lives in SKILL.md.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import tomllib

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
        "bun",
    ],
    "browser": [
        "playwright",
        "cypress",
        "puppeteer",
        "selenium",
        "webdriverio",
        "testcafe",
        "nightwatch",
        "cucumber",
    ],
    "cli": [
        "bats",
        "aruba",
        "cram",
        "pytest-console-scripts",
        "bun",
    ],
    "sdk": [
        "doctest",
        "hypothesis",
        "fast-check",
        "bun",
        "pytest-bdd",
        "behave",
        "gauge",
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
    "bun": [("bunfig.toml", None)],
    "cucumber": [
        ("cucumber.js", None),
        ("cucumber.json", None),
        (".cucumberrc", None),
        (".cucumberrc.json", None),
    ],
    "behave": [
        ("behave.ini", None),
        (".behaverc", None),
        ("pyproject.toml", "[tool.behave]"),
        ("setup.cfg", "[behave]"),
    ],
    "pytest-bdd": [
        ("pyproject.toml", '"pytest-bdd"'),
        ("pyproject.toml", '"pytest-bdd>'),
        ("pyproject.toml", '"pytest-bdd~'),
        ("pyproject.toml", '"pytest-bdd<'),
        ("pyproject.toml", '"pytest-bdd='),
    ],
    "gauge": [("manifest.json", '"Plugins":')],
}

# Surfaces where has_tooling=False means "no config-file signal," NOT
# "tool absent." sdk's doctest/hypothesis run inline; message_event's
# testcontainers et al. wire in via test code. (sdk's BDD tools
# pytest-bdd/behave/gauge DO have config signals — they're the minority,
# so a doctest-only repo still reports False here.)
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


_MONOREPO_NO_SIGNAL = {"is_monorepo": False, "kind": None, "packages": []}


def detect_monorepo(repo_root: Path) -> dict:
    """Detect monorepo structure via priority-ordered config-file signals.

    Returns ``{"is_monorepo": bool, "kind": str | None, "packages": list[str]}``.
    Priority (first match wins): pnpm > turbo > nx > lerna > workspaces (npm
    or yarn, by lock-file presence) > cargo > multi-pyproject. ``packages``
    holds repo-relative posix directory paths, glob-expanded against on-disk
    workspace members. ``is_monorepo=False`` when no signal fires.

    Hand-parsed pnpm-workspace.yaml is conservative: comment lines skipped;
    bail to the ``packages/*`` default on parse oddity rather than crash.
    Cargo + multi-pyproject use ``tomllib`` (Python 3.11+; the project floor
    was raised to 3.11 by decision; pre-commit and CI run 3.11+).

    The nx walk is bounded to ``packages/``, ``apps/``, ``libs/`` (the nx
    convention) to avoid over-collecting incidental ``project.json`` files.
    """
    pnpm = repo_root / "pnpm-workspace.yaml"
    if pnpm.is_file():
        patterns = _parse_pnpm_workspace(pnpm) or ["packages/*"]
        return {
            "is_monorepo": True,
            "kind": "pnpm",
            "packages": _expand_globs(repo_root, patterns),
        }

    turbo = repo_root / "turbo.json"
    if turbo.is_file():
        patterns = _read_package_workspaces(repo_root) or ["packages/*"]
        return {
            "is_monorepo": True,
            "kind": "turbo",
            "packages": _expand_globs(repo_root, patterns),
        }

    nx = repo_root / "nx.json"
    if nx.is_file():
        return {
            "is_monorepo": True,
            "kind": "nx",
            "packages": _walk_nx_projects(repo_root),
        }

    lerna = repo_root / "lerna.json"
    if lerna.is_file():
        try:
            patterns = json.loads(lerna.read_text(encoding="utf-8")).get(
                "packages", ["packages/*"]
            )
        except (OSError, json.JSONDecodeError):
            patterns = ["packages/*"]
        return {
            "is_monorepo": True,
            "kind": "lerna",
            "packages": _expand_globs(repo_root, patterns),
        }

    pkg = repo_root / "package.json"
    if pkg.is_file():
        patterns = _read_package_workspaces(repo_root)
        if patterns:
            kind = (
                "yarn-workspaces"
                if (repo_root / "yarn.lock").is_file()
                else "npm-workspaces"
            )
            return {
                "is_monorepo": True,
                "kind": kind,
                "packages": _expand_globs(repo_root, patterns),
            }

    cargo = repo_root / "Cargo.toml"
    if cargo.is_file():
        try:
            data = tomllib.loads(cargo.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        workspace = data.get("workspace") if isinstance(data, dict) else None
        if isinstance(workspace, dict):
            # Explicit [workspace] table is the signal — even an empty members
            # list still asserts "this is a Cargo workspace". Honesty over
            # silent fallthrough.
            members = workspace.get("members", [])
            members = members if isinstance(members, list) else []
            return {
                "is_monorepo": True,
                "kind": "cargo",
                "packages": _expand_globs(repo_root, members),
            }

    pyprojects = sorted(
        list(repo_root.glob("*/pyproject.toml"))
        + list(repo_root.glob("*/*/pyproject.toml"))
    )
    if len(pyprojects) >= 2:
        return {
            "is_monorepo": True,
            "kind": "multi-pyproject",
            "packages": [
                p.parent.relative_to(repo_root).as_posix() for p in pyprojects
            ],
        }

    return dict(_MONOREPO_NO_SIGNAL)


_PNPM_PACKAGES_LINE = re.compile(r'^\s*-\s+["\']?([^"\'#]+?)["\']?\s*(?:#.*)?$')


def _parse_pnpm_workspace(yaml_path: Path) -> list[str]:
    """Hand-parse a pnpm-workspace.yaml `packages:` list. Conservative.

    Accepts the `packages:` key at any indentation (root or nested under a
    parent map). Stops at a sibling top-level key (column-0 non-blank line
    that isn't `packages:` itself).
    """
    try:
        text = yaml_path.read_text(encoding="utf-8")
    except OSError:
        return []
    in_packages = False
    patterns: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped == "packages:":
            in_packages = True
            continue
        if in_packages:
            if line and not line.startswith((" ", "\t")):
                break
            m = _PNPM_PACKAGES_LINE.match(line)
            if m:
                patterns.append(m.group(1).strip())
    return patterns


def _read_package_workspaces(repo_root: Path) -> list[str]:
    pkg = repo_root / "package.json"
    if not pkg.is_file():
        return []
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    ws = data.get("workspaces")
    if isinstance(ws, list):
        return [p for p in ws if isinstance(p, str)]
    if isinstance(ws, dict):
        packages = ws.get("packages", [])
        if isinstance(packages, list):
            return [p for p in packages if isinstance(p, str)]
    return []


def _walk_nx_projects(repo_root: Path) -> list[str]:
    """Collect parent dirs of project.json under nx convention dirs only."""
    found: list[str] = []
    for top in ("packages", "apps", "libs"):
        top_dir = repo_root / top
        if not top_dir.is_dir():
            continue
        for proj in top_dir.rglob("project.json"):
            if proj.parent.is_dir():
                found.append(proj.parent.relative_to(repo_root).as_posix())
    return sorted(set(found))


def _expand_globs(repo_root: Path, patterns: list[str]) -> list[str]:
    """Expand workspace globs to repo-relative posix directory paths."""
    matches: set[str] = set()
    for pattern in patterns:
        for hit in repo_root.glob(pattern):
            if hit.is_dir():
                matches.add(hit.relative_to(repo_root).as_posix())
    return sorted(matches)
