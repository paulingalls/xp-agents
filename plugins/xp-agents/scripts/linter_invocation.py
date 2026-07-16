#!/usr/bin/env python3
"""How to INVOKE a linter — the argv, and whether it may run here at all.

Extracted from `linters` at the commit that pushed it past the 500-line cap. The
split is by responsibility, not by line count: `linters` is the TABLES (what claims
a file, and each row's structural facts), and this module is the JUDGEMENT built on
them (compose the argv; decide whether this linter can be run, and whether the gate
may block on it).

Every name here is re-exported from `linters` BY IDENTITY, so `linters.linter_argv`
and `linter_invocation.linter_argv` are the same object. Callers and tests that
already reach through `linters` keep working, and a patch on either name intercepts
the same function.
"""

import json
from pathlib import Path

# Imported as a MODULE as well as by name, and the alias is load-bearing: a `match`
# case treats a bare name as a capture pattern (it would bind, and match anything),
# so every shape constant compared below has to be reached through a dotted name.
import linters as _linters
from linters import (
    CONFIG_STYLE_FLAGS,
    DEGRADED_LINTERS,
    LINTER_ARGV_SHAPES,
    LINTER_COMMANDS,
    LINTER_CONFIG_FLAGS,
    LINTER_PRECONDITIONS,
    LINTER_STDIN_SHAPES,
    LINTER_STRICT_FLAGS,
    NO_PER_FILE_ARGV,
    NO_STDIN,
    PATHS_BEFORE_SEPARATOR,
    SEPARATOR_BEFORE_PATHS,
)


def linter_command(linter_name: str) -> list[str]:
    """The argv to invoke `linter_name` with, strictness flags included.

    Single source for both the edit-time (`run_linter`) and commit-time
    (`run_linter_batch`) paths, so the two cannot disagree about how strict the
    linter is. That matters: if the commit gate blocked on a warn-level finding
    that edit-time never surfaced, the agent would be ambushed at commit by a
    rule nothing had told it about.

    Prefer `linter_argv`, which also places the paths. This remains the composition
    step, and stays public because callers still pin the flags.
    """
    return LINTER_COMMANDS[linter_name] + LINTER_STRICT_FLAGS.get(linter_name, [])


def _config_style_flags(config_path: str | None) -> list[str]:
    """Flags this CLI accepts only under the config style `config_path` selects.

    Keyed on the config FILE's name — the file is what selects the mode, and the
    linter's name cannot tell you which mode it is in. See CONFIG_STYLE_FLAGS.

    No config path means the mode is unknown, and unknown answers NOTHING: a flag the
    tool might reject is worse than the warning it would have suppressed, because a
    rejected flag exits non-zero with output and the gate reads that as findings.
    """
    if not config_path:
        return []
    return CONFIG_STYLE_FLAGS.get(Path(config_path).name, [])


def _argv_prefix(linter_name: str, config_path: str | None) -> list[str] | None:
    """Everything before the paths: command, strictness, config, config-style flags.

    Shared by `linter_argv` and `linter_stdin_argv` so the two cannot disagree about
    how the linter is configured. Only WHERE the source comes from differs between
    them, and that is the only thing they should decide separately.

    None means "must not run here": a config-required linter with no config would
    otherwise run against its built-in default — a different project's rules, read
    back as either findings or clean. Both are lies.
    """
    argv = list(linter_command(linter_name))

    config_flag = LINTER_CONFIG_FLAGS.get(linter_name)
    if config_flag is not None:
        if not config_path:
            return None
        argv += [*config_flag, config_path]

    # Composed HERE, beside the strictness flags, because it only exists to answer
    # them: `--max-warnings=0` is what turns eslint's ignored-file warning into a
    # block. Pin strictness in one place and its antidote in another, and a caller
    # gets the block back. See CONFIG_STYLE_FLAGS.
    return argv + _config_style_flags(config_path)


def _compile_db_covers(root: str, paths: list[str], base: str) -> bool:
    """Can the compile database supply build flags for EVERY one of `paths`?

    Existence is not coverage, and the difference is an unfixable block. A partial or
    stale database — one that names `src/` while the staged file lives under `tests/`
    — leaves that file with no include flags, so clang-tidy cannot COMPILE it:
    `'t.h' file not found [clang-diagnostic-error]`, non-zero, with output, which the
    gate reads as FINDINGS. The committer cannot fix that by fixing the diff; they
    have to regenerate the database, which is a build step. Partial databases are the
    ordinary case (a new file, a test subtree, generated sources, a DB nobody re-ran).

    Coverage is by DIRECTORY, not by exact filename, because clang-tidy INFERS a
    command for a file the database does not name from its covered siblings. Matching
    names exactly would degrade every newly-added source and quietly hand C/C++ back
    the non-gate this story exists to remove.

    `root` locates the DATABASE; `base` is the directory `paths` are relative TO, and
    they are NOT the same directory — conflating them was an unfixable block. The
    database sits at the git root, but a linter runs FROM its config file's directory
    (`lint_check.lint_invocation_target`), so its paths are relative to THAT. With a
    `.clang-tidy` one level down — the ordinary C/C++ layout — `src/app.c` arrives
    here as `app.c`, resolves to `<root>/app.c`, matches no covered directory, and a
    file the database covers perfectly well is refused. Ask the caller where its paths
    came from; never assume.

    Unreadable or malformed database → NOT covered. The safe direction here is
    "advise", never "block": we lose a little coverage, instead of handing the user a
    gate whose only escape is to switch it off.
    """
    db = Path(root) / "compile_commands.json"
    try:
        entries = json.loads(db.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(entries, list):
        return False

    covered_dirs: set[Path] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        named = entry.get("file")
        if not isinstance(named, str) or not named:
            continue
        p = Path(named)
        if not p.is_absolute():
            p = Path(entry.get("directory") or root) / p
        covered_dirs.add(p.parent.resolve())

    if not covered_dirs:
        return False

    base_path = Path(base)
    return all((base_path / p).resolve().parent in covered_dirs for p in paths)


def preconditions_met(
    linter_name: str, root: str, paths: list[str], *, base: str | None = None
) -> bool:
    """Can this linter actually be RUN over `paths`, here, in this checkout?

    Not a property of the linter — a property of the checkout AND the files. See
    LINTER_PRECONDITIONS. A row with no precondition is always met.

    The `paths` argument is the whole point, and its absence was a bug: the first
    version asked only "does compile_commands.json exist at the root?", which is a
    different question from "can clang-tidy compile this staged file?" — and they come
    apart exactly where it hurts. See `_compile_db_covers`.

    `base` names the directory `paths` are relative to; it defaults to `root` for the
    caller that reads them straight out of `git diff --cached` (root-relative), and
    must be passed by the callers that hand over the linter's OWN argv paths, which
    are relative to the directory it will run in. See `_compile_db_covers`.
    """
    required = LINTER_PRECONDITIONS.get(linter_name)
    if required is None:
        return True
    if not (Path(root) / required).exists():
        return False
    if required == "compile_commands.json":
        return _compile_db_covers(root, paths, base or root)
    return True


def linter_argv(
    linter_name: str,
    paths: list[str],
    *,
    root: str,
    config_path: str | None = None,
    base: str | None = None,
) -> list[str] | None:
    """The FULL argv to run `linter_name` over `paths`, or None if it must not run.

    The single source of argv for BOTH the edit-time (`run_linter`) and commit-time
    (`run_linter_batch`) paths. It has to be single: the separator used to be placed
    by each caller separately, and that duplication is exactly where clang-tidy's
    broken invocation lived — the commit path was patched around it by degrading the
    row, while the EDIT path went on building `clang-tidy -- app.c` and linting
    nothing at all.

    Returns None for "we must not run this here", which is NOT "it ran and found
    nothing". Three ways to earn it, and every caller has to honour all three:

      * an unmet precondition (clang-tidy with no compile database) — the edit-time
        path would otherwise raise a concern the resolution path can never clear:
        `'hdr.h' file not found` is not fixable by editing the file it is attached to;
      * a config-required linter with no config (checkstyle);
      * a linter with no per-file argv AT ALL (clippy lints the crate, not a file).

    On the separator, note what this does NOT do: clang-tidy gets NO trailing `--`.
    The debt that asked for this fix prescribed one, and that half of its prescription
    is wrong — a trailing `--` means "no compiler flags", which OVERRIDES
    compile_commands.json and throws away the very database that lets clang-tidy
    resolve an `#include`. Since the row is only ever invoked WITH a database (the
    precondition above), there is no case left in which appending it would be right.

    `base` is the directory `paths` are relative to — i.e. the cwd this argv will be
    RUN from. Pass it whenever that differs from `root` (it does whenever the config
    file lives in a subdirectory), or the precondition resolves the paths against the
    wrong directory and refuses to build an argv it should have built.

    A precondition is judged on `paths` themselves, with nothing to thread through:
    every caller now lints the real file. The commit gate used to lint materialized
    temp copies, so it had to hand over the REAL staged paths separately — a
    compile-DB's directory coverage is a fact about the real file, and a temp copy in
    a subdir of a covered directory reads as uncovered though the real file is not.
    Nothing copies any more, so the two questions have one answer again.
    """
    if not preconditions_met(linter_name, root, paths, base=base):
        return None

    shape = LINTER_ARGV_SHAPES.get(linter_name, SEPARATOR_BEFORE_PATHS)
    if shape == NO_PER_FILE_ARGV:
        return None

    argv = _argv_prefix(linter_name, config_path)
    if argv is None:
        return None

    if shape == PATHS_BEFORE_SEPARATOR:
        return [*argv, *paths]
    return [*argv, "--", *paths]


def linter_stdin_argv(
    linter_name: str,
    path: str,
    *,
    root: str,
    config_path: str | None = None,
    base: str | None = None,
) -> list[str] | None:
    """The argv to lint bytes arriving on STDIN *as if* they were `path`.

    The commit gate's answer to the case where the index and the working tree
    disagree: the bytes to judge are not on disk, and every place we could put them
    is the wrong place. A temp sibling takes a random basename and defeats
    filename-keyed rules; a temp subdir keeps the basename but sits one level down,
    so the file's own `./util` and `../lib/x` resolve to paths that do not exist.
    Both properties hold only at the real path — so hand the linter the bytes and
    TELL it the path, and no copy exists at all.

    One path, not many: stdin carries one file. The caller pays that cost only for
    files that actually diverge.

    Returns None for "we must not do this here", which is NOT a clean result:

      * this CLI reads no source on stdin (LINTER_STDIN_SHAPES has no row) — the
        default, so a linter nobody filled in lands here rather than being handed
        an argv it never agreed to;
      * an unmet precondition, or a config-required linter with no config — the
        same two refusals `linter_argv` makes, for the same reasons.

    See LINTER_STDIN_SHAPES for why the shape is a shape and not a bool.
    """
    shape = LINTER_STDIN_SHAPES.get(linter_name, NO_STDIN)
    if shape == NO_STDIN:
        return None

    if not preconditions_met(linter_name, root, [path], base=base):
        return None

    argv = _argv_prefix(linter_name, config_path)
    if argv is None:
        return None

    match shape:
        case _linters.STDIN_FILENAME_TRAILING_DASH:
            # The trailing `-` is the PATH argument, and it is what selects stdin;
            # --stdin-filename only labels the bytes. Drop the `-` and ruff lints
            # the whole directory instead (its path default is `.`).
            return [*argv, "--stdin-filename", path, "-"]
        case _linters.STDIN_FLAG_AND_FILENAME:
            return [*argv, "--stdin", "--stdin-filename", path]
        case _linters.STDIN_FILEPATH:
            return [*argv, "--stdin-filepath", path]
    return None


def degrade_reason(
    linter_name: str,
    root: str,
    paths: list[str] | None = None,
    *,
    base: str | None = None,
) -> str | None:
    """Why the commit gate must not BLOCK on this linter here, or None if it may.

    Three different answers to one question — "can the gate block on this row?" — and
    the old code collapsed them into a single set with a single blanket message. They
    are not the same, and the customer deserves the real one:

      * the linter judges the whole project, not one file (clippy);
      * its exit code cannot express what it found (checkstyle);
      * this checkout lacks something it needs (clang-tidy without a compile DB).

    `base` defaults to `root`, which is right for the commit gate — it asks this with
    the paths git named, and git names them from the root. See `_compile_db_covers`.
    """
    static = DEGRADED_LINTERS.get(linter_name)
    if static is not None:
        return static
    required = LINTER_PRECONDITIONS.get(linter_name)
    if required is not None and not preconditions_met(
        linter_name, root, paths or [], base=base
    ):
        return (
            f"this project has no {required}, so {linter_name} cannot resolve "
            f"includes — it would fail to COMPILE the file and block on an error "
            f"your diff cannot fix"
        )
    return None


def is_file_scoped(
    linter_name: str,
    root: str,
    paths: list[str] | None = None,
    *,
    base: str | None = None,
) -> bool:
    """Can the commit gate BLOCK on this linter, in THIS project?

    False where a non-zero exit would report something the staged diff neither caused
    nor can fix. A gate that cannot be satisfied is worse than one that stays quiet,
    because the first thing anyone does with an unfixable gate is disable it.

    Unknown rows answer True: a linter nobody classified is far likelier to be an
    ordinary file-scoped one than a project sweep, and being wrong that way produces
    a too-strict block the agent can actually act on.
    """
    return degrade_reason(linter_name, root, paths, base=base) is None
