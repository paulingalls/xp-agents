#!/usr/bin/env python3
"""In-place teammate marker: lifetime-scoped presence + pid-liveness.

A solo/in-place teammate runs in the MAIN checkout, so — unlike a worktree
teammate — its cwd carries no path marker to identify it by. This marker is
that missing signal. It is written by `spawn_teammate --in-place` and read by
two consumers that pull in OPPOSITE directions, which is the whole design
problem here:

  - `in_place_marker_exists` (existence-only) — identity, pre_tool_skill and
    commit_handling pair it with a non-None XP_TEAMMATE_NAME to decide whether
    a process IS a teammate. A LIVE teammate must never lose its marker, or it
    is demoted to the lead: skill gating drops and its commits are misattributed.

  - `has_live_in_place_teammate` (pid-liveness) — the accept gate has no name to
    pair with, so it pays for a liveness probe. A DEAD teammate must never
    suppress the gate, or `/xp-accept` certifies a half-written tree.

Reconciling the two is what the pid list buys: the marker records every process
whose life means the episode is still in flight, reads live while ANY survives,
and is reaped only once ALL are PROVEN dead — the sole condition under which
neither consumer can be harmed.

Split from worktree.py (which crossed the 500-line ceiling); re-exported there,
so `worktree.<name>` remains the import surface for existing call sites.
"""

import contextlib
import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import marker_names


def in_place_marker_path(smm_dir: Path, name: str) -> Path:
    """Return the path to an in-place teammate's lifetime-scoped active marker."""
    return smm_dir / marker_names.IN_PLACE_ACTIVE.format(name=name)


class InPlaceNameHeld(Exception):
    """A live (or unadjudicable) in-place teammate already holds this name.

    Refusing is the point. Two live teammates under one name is the state the
    marker exists to prevent: whichever of them writes last owns the content, and
    the other's teardown then deletes a LIVE teammate's marker. Failing the spawn
    LOUDLY is recoverable (kill the holder, or inspect and rm a corrupt marker);
    silently demoting a running teammate to the lead is not.
    """


_CLAIM_ATTEMPTS = 3


def _publish_exclusive(path: Path, content: str) -> bool:
    """Link a fully-written file into `path`. False when the path is taken.

    `os.link` fails with EEXIST rather than replacing, which is what makes taking
    the name atomic against a concurrent claimant — a plain check-then-write
    lets two supervisors both read "free" and both write.

    The content is written to the temp file BEFORE it is linked, so the marker is
    never observable at `path` in a partial state. Publishing by O_EXCL-creating
    `path` and then writing to it would instead expose a ZERO-BYTE marker for the
    width of that write — and a supervisor dying in that window leaks an EMPTY
    marker, which reads "not alive" but is NOT proof of death, so the reap never
    collects it (see _marker_pid_alive). It would refuse every same-name respawn
    forever. Link-after-write makes that window structurally nonexistent.

    A symlink at `path` counts as taken (link does not follow the destination),
    so the writer keeps refusing to write through one, as it always has.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp, 0o600)
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        return True
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def claim_in_place_marker(smm_dir: Path, name: str) -> None:
    """Take the name for this supervisor, or raise InPlaceNameHeld.

    The FIRST of the episode's two marker writes, and the one that makes the name
    exclusive. It used to be an unconditional atomic rename, which is a WRITE door
    onto the same disaster the two delete guards close: spawning over a live
    teammate B clobbered B's marker with our pids, and our `finally` then read our
    own pid at the front, passed its ownership check, and deleted B's marker. A
    writer can always FORGE the content proof against itself — which is why
    ownership has to be established by taking the name, not by writing it.

    On collision the holder is ADJUDICATED rather than blindly refused or blindly
    clobbered, and the three verdicts are the same three the reap uses:

      - LIVE -> refuse. Two live teammates under one name is the state we never
        want.
      - PROVEN dead -> _marker_pid_alive reaps it (guarded: it unlinks only the
        inode it proved dead), and the retry takes the freed path. This is the
        kill-then-respawn recovery flow, and it is why an always-exclusive claim
        would be wrong: a SIGKILLed supervisor skips its `finally` and leaks its
        marker ROUTINELY, so refusing on any existing marker would permanently
        block every respawn.
      - unadjudicable -> not reaped (it is not proof of death, and may belong to a
        live teammate running older code), so the retries exhaust and we refuse.
        Recoverable by inspecting and removing it.

    Content is the pid list — every process whose life means the episode is still
    in flight — so has_live_in_place_teammate can probe liveness without knowing
    the name. Only ours exists yet; the child's is folded in by
    rewrite_own_in_place_marker once Popen returns.
    """
    path = in_place_marker_path(smm_dir, name)
    for _ in range(_CLAIM_ATTEMPTS):
        if _publish_exclusive(path, str(os.getpid())):
            return
        if _marker_pid_alive(path):
            raise InPlaceNameHeld(
                f"a live in-place teammate already holds {name!r} ({path}). "
                "Kill its recorded processes — the supervisor AND its child — "
                "before respawning."
            )
        # Not live. _marker_pid_alive reaped it IFF every pid was proven dead, so
        # the retry either takes the freed path or finds the same unadjudicable
        # marker still there and we fall through to the refusal below.
    raise InPlaceNameHeld(
        f"cannot claim {name!r}: {path} is held by a marker that is neither live "
        "nor provably dead (a legacy, corrupt, or foreign-owned marker). Inspect "
        "it and remove it to respawn."
    )


def rewrite_own_in_place_marker(smm_dir: Path, name: str, child_pid: int) -> None:
    """Fold the child's pid into the marker, but only while it is still OURS.

    The SECOND of the episode's two writes. The child is the actual teammate and
    can OUTLIVE this supervisor (we are only a tee; a SIGKILL up here does not
    propagate to it), so its pid is the one that must keep the marker alive after
    we die — recording only ours would let the reap collect a LIVE teammate's
    marker.

    Guarded for the same reason the deletes are: an unconditional write here
    re-forges the ownership the `finally` goes on to check. The claim already
    stops a respawn appearing under a LIVE supervisor, so what this covers is the
    case the claim cannot — the marker cleared out-of-band (an operator rm'ing a
    "stuck" marker) and re-claimed by a respawn while we are still running. With
    the guard, EVERY mutation of this path is either an exclusive create from
    nothing or an ownership-checked write by its creator; without it, that
    invariant has a hole and the delete guards inherit it.

    Declining is the safe direction: our child's pid simply goes unrecorded, so
    the episode reads dead once WE exit. That fails OPEN (the accept gate fires),
    which is the direction the whole module leans.

    Stays atomic (mkstemp + rename ⇒ a NEW inode), which the reap's identity guard
    depends on — test_the_rewrite_publishes_a_new_inode pins it.
    """
    from _append_impl import write_text_atomic

    path = in_place_marker_path(smm_dir, name)
    with _pinned_marker(path) as pinned:
        if pinned is None:
            return  # gone, symlinked, unreadable: nothing of ours to rewrite
        _, tokens = pinned
        if not tokens or tokens[0] != str(os.getpid()):
            return  # a respawn's marker (or a legacy one) — not ours to rewrite
    write_text_atomic(path, f"{os.getpid()} {child_pid}")


def remove_own_in_place_marker(smm_dir: Path, name: str) -> None:
    """Remove the marker only while it is OURS and unchanged. Idempotent.

    The ONLY way this module deletes a marker by name. The supervisor's teardown
    is the second of the two doors onto the same disaster (the reap is the
    other), with the same blast radius: a same-name teammate respawned while this
    supervisor is still running would have its LIVE marker deleted by our
    `finally`, demoting it to the lead and misattributing its commits.
    Kill-then-respawn is the documented recovery for a stuck teammate, so this is
    a routine window, not an exotic one. An unguarded sibling that "just unlinks"
    would be the next person's default reach and would silently reopen it, which
    is why no such helper exists.

    Ownership is proven by CONTENT, not by a stat remembered from write time. The
    marker's first pid is the supervisor that wrote it — us (see
    claim_in_place_marker, which always records os.getpid() first) — and a pid
    cannot be recycled while its own process is alive, so no respawn can forge
    it. Content is the right predicate precisely because it is unforgeable.

    A remembered stat could NOT do this job: write_text_atomic is mkstemp+rename,
    so any stat taken after it is a stat BY PATH, and a respawn landing in that
    window would poison the remembered identity — the finally would then delete
    the respawn's marker, which is the exact bug being fixed.

    Both legs are needed and neither is redundant:
      - content proves the marker is ours (a different supervisor => not ours);
      - inode identity, fstat'd on the very fd the content was read through,
        proves it has not been replaced since we read it (_unlink_if_unchanged).
    The fd is held open across both, pinning the inode against reuse.

    Fail-safe in one direction only, like the reap: anything we cannot adjudicate
    means we cannot prove the marker is ours, so we do NOT delete it. A leaked
    marker is harmless — it reads dead and the reap collects it later.

    One premise this CANNOT check, and its caller must: that we wrote the marker
    now at the path. "First pid is ours" is unforgeable only against a LIVE
    writer; a marker leaked by a SIGKILLed supervisor names a DEAD pid, and a
    dead pid can be recycled to us while its orphaned child keeps the marker
    live. spawn_teammate therefore calls this only once its own write has landed.
    """
    path = in_place_marker_path(smm_dir, name)
    with _pinned_marker(path) as pinned:
        if pinned is None:
            return  # gone, symlinked, unreadable: nothing of ours to remove
        identity, tokens = pinned
        if not tokens or tokens[0] != str(os.getpid()):
            return  # a respawn's marker (or a legacy one) — not ours to delete
        _unlink_if_unchanged(path, identity)


def in_place_marker_exists(smm_dir: Path, name: str) -> bool:
    """True when an in-place teammate marker exists for `name`.

    Deliberately existence-only, NOT pid-liveness like has_live_in_place_teammate
    below: every caller pairs this with a non-None XP_TEAMMATE_NAME, and that
    pairing is what makes a leaked marker inert for them. Adding a liveness probe
    here to "match" would flip the fail direction for those callers — a probe
    misfire would demote a LIVE teammate to the lead and lose its commit
    attribution. The gate's name-free probe has no name to pair with, which is
    why it (and only it) pays for liveness.
    """
    return in_place_marker_path(smm_dir, name).is_file()


def _probe_pid(pid: int) -> bool | None:
    """True = alive, False = PROVEN dead, None = cannot adjudicate.

    POSIX-only: os.kill(pid, 0) is a liveness probe here, but on Windows it
    would terminate the target. The plugin is already POSIX (flock, bash
    preloads), so this is a note, not a branch.

    "Proven dead" is a strictly narrower claim than "not alive", and only the
    former may authorize a reap — hence three states, not two.
    """
    if pid <= 0:
        # os.kill(0, 0) signals our OWN process group and SUCCEEDS; negative
        # pids are process-GROUP targets. Neither is a pid we wrote, so this is
        # corruption: not alive, but not proof of death either.
        return None
    try:
        os.kill(pid, 0)
    except OverflowError:
        # int() is arbitrary-precision but os.kill needs a C int. OverflowError
        # is an ArithmeticError, so it escapes the OSError clauses below and
        # would CRASH the Stop hook -- a crash means the gate never fires at all.
        return None
    except ProcessLookupError:
        return False  # proven dead
    except OSError:
        # PermissionError: the pid EXISTS but is owned by another uid, so it is
        # not our teammate (which runs as us) — unadjudicable, and certainly not
        # proof of death.
        return None
    return True


def _read_all(fd: int) -> bytes:
    """Read `fd` to EOF.

    os.read returns what a single read syscall yields, which may be short; the
    loop is what makes "the bytes I probed" the WHOLE file. Reading through the
    descriptor (rather than path.read_text) is what lets the caller fstat the
    exact inode the bytes came from.
    """
    chunks: list[bytes] = []
    while chunk := os.read(fd, 4096):
        chunks.append(chunk)
    return b"".join(chunks)


@contextlib.contextmanager
def _pinned_marker(
    path: Path,
) -> Iterator[tuple[tuple[int, int, int, int], list[str]] | None]:
    """Open the marker and yield (identity, tokens), or None if unadjudicable.

    The single place the marker is read. BOTH readers — the reap and the
    supervisor's teardown — go on to unlink based on what they find here, so all
    three of this function's subtleties are load-bearing for both, and having
    them in one place is what stops a future edit to one reader from silently
    reopening a hole in it:

      - O_NOFOLLOW mirrors the writer's symlink rejection: a symlinked marker is
        not something we wrote, and refusing to read it fails in the safe
        direction for both callers (reads dead / not ours).
      - identity comes from FSTAT on the very descriptor the bytes came from, so
        the content probed and the identity later compared are provably the same
        inode. A stat BY PATH could describe a different file than the one read.
      - the descriptor stays open for the whole `with` body — i.e. through the
        caller's _unlink_if_unchanged. An open fd pins its inode even at
        nlink=0, so the kernel cannot recycle that inode number into a
        concurrent mkstemp during the compare. That makes inode reuse a
        structural impossibility here rather than a low probability; closing the
        fd right after the read would silently reinstate the gap.

    Yields None on anything unreadable — vanished, symlinked, non-UTF-8 (a
    UnicodeDecodeError is a ValueError). Letting those escape would crash the
    Stop hook, and a crashed gate never fires at all.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        yield None
        return
    try:
        try:
            identity = _identity(os.fstat(fd))
            tokens = _read_all(fd).decode().split()
        except (OSError, ValueError):
            yield None
            return
        yield identity, tokens
    finally:
        os.close(fd)


def _identity(st: os.stat_result) -> tuple[int, int, int, int]:
    """A marker's structural identity: "is this still the file I read?".

    st_ino is the load-bearing component, and it is a STRUCTURAL invariant here,
    not a probabilistic one: the only two production writers are the claim (which
    LINKS a fresh file into the path) and the rewrite (mkstemp + rename), so there
    is no in-place mutation path anywhere — every marker write lands a NEW inode by
    construction. A respawn's marker therefore CANNOT share an inode with the one
    it replaced. (test_rewriting_the_marker_changes_the_inode pins that coupling;
    the guard is silently disarmed if a writer ever mutates in place.)

    st_dev pairs with st_ino because inode numbers are only unique per device.
    st_mtime_ns and st_size ride along as free extras — the same single stat call
    — but correctness must never rest on them: a timestamp is not a structural
    invariant, and a coarse filesystem mtime clock (1-4ms on ext4/tmpfs) cannot
    resolve two writes microseconds apart.
    """
    return (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)


def _unlink_if_unchanged(path: Path, identity: tuple[int, int, int, int]) -> None:
    """Unlink `path` only while it is still the inode whose pids were proven dead.

    `unlink` targets the PATH, so it deletes whatever inode sits there NOW — not
    the one that was read. A same-name respawn (the documented recovery for a
    stuck teammate) can rename a fresh marker into place during the probe, and
    deleting THAT demotes a live teammate to the lead and misattributes its
    commits.

    Fail-safe in one direction only: cannot prove the file is the one we proved
    dead -> do not delete it. A skipped reap is harmless (the leaked marker reads
    dead and suppresses nothing; the next Stop reaps it), so an OSError here is
    simply another reason not to unlink.

    lstat, not stat: a symlink that appeared at the path since the read is not
    the file we read, whatever it points at.
    """
    try:
        current = _identity(os.lstat(path))
    except OSError:
        return
    if current != identity:
        return
    path.unlink(missing_ok=True)


def _marker_pid_alive(path: Path) -> bool:
    """True when ANY process recorded in the marker is still alive.

    The marker lists the supervising spawn_teammate AND the `claude` child it
    launched. Both must be probed, because the child can OUTLIVE the supervisor:
    the supervisor is only a tee (plain Popen, no start_new_session), so a
    SIGTERM/SIGKILL delivered to its pid does NOT propagate to the child. The
    child is reparented to init and keeps running — indefinitely, if it is mid
    silent stretch (a long model call; the watchdog tolerates 900s of these).
    Only a chatty child dies promptly, on BrokenPipe at its next stdout write.
    Probing the supervisor alone would therefore read DEAD while a live teammate
    is still writing the tree, firing the accept gate mid-flight AND reaping the
    live teammate's marker out from under it (demoting it to the lead).

    Leaks are routine, not exotic: Python installs no SIGTERM handler, so
    spawn_teammate's marker-removing `finally` does NOT run when a backgrounded
    spawn is cancelled (the usual kill path) — only on a clean exit or SIGINT.
    An unreadable/unparseable marker therefore fails OPEN (reads dead -> the gate
    fires): a suppressed accept gate certifies a half-written tree silently,
    whereas a spurious one merely nags.

    Reaping is the opposite bet and needs the opposite bar. A marker is unlinked
    only when EVERY recorded pid is PROVEN dead — the one condition under which
    no consumer can be harmed. That keeps leaks from accumulating until a
    recycled pid reads live again and re-suppresses the gate, without ever
    deleting the marker of a teammate that is merely un-adjudicable.

    The read and the unlink are separated by N os.kill syscalls, and `unlink`
    deletes by PATH — so the marker it removes need not be the one whose pids it
    proved dead. The identity captured by _pinned_marker bounds that: the unlink
    happens only while the same inode is still at the path (_unlink_if_unchanged),
    and the fd stays pinned across the whole compare. See _pinned_marker for why
    fstat-not-stat and the held descriptor are what make that airtight.

    The guard attaches to the UNLINK only, never to the return value: every path
    below still reads dead on anything it cannot adjudicate, so the fail-open
    contract above is untouched. Declining to reap can only ever leak a marker,
    and a leaked marker reads dead and suppresses nothing.
    """
    with _pinned_marker(path) as pinned:
        # Vanished mid-scan (spawn_teammate's finally), symlinked, or unreadable.
        if pinned is None:
            return False
        identity, tokens = pinned
        try:
            # A legacy name-content marker may belong to a teammate still running
            # the older code — unadjudicable, NOT reaped.
            pids = [int(t) for t in tokens]
        except ValueError:
            return False
        if not pids:
            return False  # empty marker: not alive, but not proof of death
        verdicts = [_probe_pid(p) for p in pids]
        if any(v is True for v in verdicts):
            return True
        if all(v is False for v in verdicts):
            _unlink_if_unchanged(path, identity)
        return False


def has_live_in_place_teammate(smm_dir: Path) -> bool:
    """True when a LIVE in-place teammate marker exists, whatever its name.

    Every marker is probed, and the verdicts are collected BEFORE they are
    aggregated: the reap is a side effect of the probe, so short-circuiting on
    the first live marker (`any(gen)`) would leak every dead marker behind it,
    and which ones got reaped would depend on the order the filesystem happened
    to yield. `sorted` pins that order so the scan is reproducible.
    """
    pattern = marker_names.IN_PLACE_ACTIVE.format(name="*")
    verdicts = [_marker_pid_alive(p) for p in sorted(smm_dir.glob(pattern))]
    return any(verdicts)


def in_place_teammate_from_env(smm_dir: Path, env_name: str | None) -> bool:
    """True when env_name names a live in-place teammate (marker present).

    Wraps the env-name-not-None + in_place_marker_exists check the three
    call sites (identity, pre_tool_skill, commit_handling) rolled by hand.
    Caller-side id-shape validation (is_teammate_agent_id) and smm_dir
    resolution stay at the call sites, which differ.
    """
    return env_name is not None and in_place_marker_exists(smm_dir, env_name)
