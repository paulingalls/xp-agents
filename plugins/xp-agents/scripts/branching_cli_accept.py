#!/usr/bin/env python3
"""The `accept-env` subcommand family: the serial main-checkout acceptance env.

Extracted from branching_cli.py to keep that module under the 500-line target.
Cohesive by collaborator and by lifecycle: every command here is one leg of the
same prepare -> (run the harness) -> restore cycle over a single shared
checkout, and acceptance_env is the only thing they talk to. They are also the
only branching_cli commands with their OWN subparser tree, so the parser wiring
travels with them (`register`) rather than being stranded in main().
"""

import argparse
import sys
from pathlib import Path

import acceptance_env


def _cmd_accept_env_prepare(args: argparse.Namespace) -> int:
    """Detach the main checkout onto a teammate story's tip; print the restore ref.

    The SKILL captures stdout (the sprint base) to pass back to
    ``accept-env restore`` after the acceptance harness runs.
    """
    try:
        tip, base = acceptance_env.resolve_story_tip(
            Path(args.smm_dir), args.cwd, args.story
        )
        acceptance_env.checkout_story_tip(args.cwd, tip)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    print(base)
    return 0


def _cmd_accept_env_restore(args: argparse.Namespace) -> int:
    """Return the main checkout to ``--restore-ref`` (the base from prepare)."""
    try:
        acceptance_env.restore(args.cwd, args.restore_ref)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


def _cmd_accept_env_recover(args: argparse.Namespace) -> int:
    """Heal an interrupted main checkout; print the recovered state (else nothing)."""
    try:
        state = acceptance_env.recover(Path(args.smm_dir), args.cwd)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    if state:
        print(state)
    return 0


def _cmd_accept_env_inspect(args: argparse.Namespace) -> int:
    """Print a read-only prepare-readiness snapshot for the /xp-accept preload.

    One TSV row per live teammate worktree:
    ``story_id<TAB>path<TAB>tip<TAB>restore_ref``. A trailing
    ``MAIN_STATE<TAB><state>`` line flags a window needing recovery before a
    detached-HEAD checkout (interrupted state, else dirty); omitted on a clean
    tree. Tab-delimited because macOS paths can contain spaces.
    """
    try:
        snap = acceptance_env.inspect(Path(args.smm_dir), args.cwd)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    for row in snap.rows:
        print(f"{row.story_id}\t{row.wt_path}\t{row.tip_sha}\t{row.restore_ref}")
    if snap.main_state:
        print(f"MAIN_STATE\t{snap.main_state}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    """Attach the `accept-env` subparser tree to branching_cli's dispatcher."""
    p_ae = sub.add_parser(
        "accept-env",
        help="Serial main-checkout acceptance env (prepare/restore/recover)",
    )
    ae = p_ae.add_subparsers(dest="accept_env_action", required=True)
    ae_prep = ae.add_parser(
        "prepare", help="Detach onto a story's tip; print the restore ref"
    )
    ae_prep.add_argument("--cwd", required=True)
    ae_prep.add_argument("--story", required=True)
    ae_prep.set_defaults(func=_cmd_accept_env_prepare)
    ae_rest = ae.add_parser("restore", help="Restore the main checkout to a ref")
    ae_rest.add_argument("--cwd", required=True)
    ae_rest.add_argument("--restore-ref", required=True)
    ae_rest.set_defaults(func=_cmd_accept_env_restore)
    ae_rec = ae.add_parser("recover", help="Heal an interrupted main checkout")
    ae_rec.add_argument("--cwd", required=True)
    ae_rec.set_defaults(func=_cmd_accept_env_recover)
    ae_insp = ae.add_parser(
        "inspect", help="Read-only prepare-readiness snapshot (rows + MAIN_STATE flag)"
    )
    ae_insp.add_argument("--cwd", required=True)
    ae_insp.set_defaults(func=_cmd_accept_env_inspect)
