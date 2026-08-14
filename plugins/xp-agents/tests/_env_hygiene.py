#!/usr/bin/env python3
"""Process-environment containment for the whole test session.

Imported by conftest for its SIDE EFFECT — importing this module strips the
variables a parent shell would otherwise leak into test subprocesses, and pins
the ones that must hold a known value. It lives apart from conftest only to
keep that file under the size ceiling; none of it is optional.

Containment belongs at ONE authoritative point. Six `_run_preload` definitions
and ten base-class `os.environ.copy()` sites consume this environment; a pin
added per-consumer covers a fraction of the surface and the next consumer opts
out by simply not knowing. Same argument as `_spawn_guard`.

A pin always goes on the TOP-preference variable in whatever chain production
code consults. A pin that something else can outrank is not containment.
"""

import atexit
import os
import shutil
import tempfile

# --- Session id -----------------------------------------------------------
#
# The hook-liveness heartbeat is keyed on the session id, so a suite that
# resolves the DEVELOPER'S real id reads and writes that developer's live
# marker. Nothing stripped a session id before this block existed: a preload
# subprocess inherited whatever the surrounding harness exported.
#
# PIN the top-preference candidate, STRIP the rest. A pin on a lower one is
# not containment — production consults the chain in order, so anything above
# it wins. Named here rather than derived by importing the production module,
# which would mean importing production code before this file has finished
# containing the environment it reads. test_preload_liveness.py asserts these
# names still equal `hook_liveness.SESSION_ID_ENV_CANDIDATES` exactly, IN ORDER,
# so a new candidate cannot be added without this list following it.
PINNED_SESSION_ID_VAR = "XP_SESSION_ID"
STRIPPED_SESSION_ID_VARS = ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID")
TEST_SESSION_ID = "xp-agents-test-session"

# The preload liveness check's escape hatch, and the suite's containment for it.
#
# Six `_run_preload` definitions drive preloads, three of them SHADOWING the
# base-class method with different signatures. Seeding a live heartbeat in one
# covers a sixth of the surface, and a seventh runner would opt out by simply
# not knowing it had to. Worse, the byte-budget path fails SILENTLY:
# `assert_preload_under_budgets` collects only outputs OVER budget, and a short
# refusal banner is under every budget — so the suite would go green while
# measuring the refusal instead of the preload.
#
# So the bypass is pinned once, here, using the escape hatch the feature ships
# anyway. The dedicated liveness suites unset it explicitly; that is where the
# real behavior is exercised.
SKIP_LIVENESS_ENV = "XP_SKIP_LIVENESS_CHECK"

# Strip environment variables that would leak a parent shell's state into
# test subprocesses.
# - GIT_*: git sets these during commits/worktrees; inheriting them makes
#   subprocess calls target the parent repo instead of the temp repo.
#   Known issue: pre-commit#3032, lefthook#1265.
# - SMM_DIR: now honored by init.sh / _append_impl.resolve_smm_dir; a stray
#   export from a dev shell would silently redirect every test's SMM writes.
# - XP_TEAMMATE_NAME: set by the CLI teammate launcher and read by both
#   identity.is_worktree_teammate (as a fallback when cwd lacks a worktree
#   marker) and the SessionStart hook (to choose the teammate guide). When
#   it leaks from a teammate shell into test subprocesses, ~50 hook /
#   integration tests get True on "non-teammate" paths or assert against
#   the wrong guide, breaking every teammate's pre-commit downstream.
# - XP_FILE_DOMAIN_DRIFT_TOLERANCE: read by sprint_cli inside
#   _cmd_validate_domain (per-invocation) to set the validate-domain
#   drift threshold. Tests that exercise that knob pass it explicitly
#   via run_cli's extra_env; a stray export from a dev shell would
#   silently flip the default-tolerance assertions in test_sprint_cli.
# - XP_AGENTS_DATA: init.sh's top-preference SMM data root. It exists precisely
#   so a user can export it from their shell, and plugin developers are users,
#   so a leak is likely rather than theoretical: every test that derives an SMM
#   would litter that real root with one project-id dir per ephemeral temp repo
#   (the regression TestPluginDataIsolation guards). Listed here to keep this
#   registry complete, but the PIN below is what contains it: that assignment
#   overwrites any leaked value, so this strip is belt to its braces.
# - XP_LOCK_TIMEOUT_SECONDS: `_append_impl`'s flock budget, and the TOP of that
#   chain — it outranks both the module default and a caller's explicit
#   `flock_with_timeout(timeout_s=...)`. A leaked export therefore rewrites
#   every acquire budget in the suite: the timeout tests that patch
#   `LOCK_TIMEOUT_SECONDS` measure the leaked value instead, and coordination's
#   own 2s becomes whatever the dev shell says. Tests that exercise the lever
#   pass it explicitly on the subprocess env (test_stop_gate_in_place,
#   test_coordination_lock), which this strip does not affect.
# - XP_SMM_MIGRATE: init.sh's relocation override. `off` suppresses relocation
#   and `force` performs it despite the teammate-liveness gate, so a leaked
#   value would either hide the migration tests' subject or drive it past the
#   very guard those tests exist to pin. The migration suite sets it
#   explicitly per case.
#
# A NAMED CONSTANT, not an inline tuple in the loop below. CLAUDE.md calls this
# module the single registry and requires `lefthook.yml` to mirror it, and a list
# spelled inline can only be mirrored by hand — which is how it came to be missing
# five of these entries with nothing to notice. `tests/test_env_strip_mirror.py`
# reads THIS tuple and scans lefthook for every `env -u` run, so the claim is now
# checked rather than asserted.
STRIPPED_VARS: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "SMM_DIR",
    "XP_TEAMMATE_NAME",
    "XP_FILE_DOMAIN_DRIFT_TOLERANCE",
    "XP_AGENTS_DATA",
    "XP_LOCK_TIMEOUT_SECONDS",
    "XP_SMM_MIGRATE",
    *STRIPPED_SESSION_ID_VARS,
)

for _leaked_var in STRIPPED_VARS:
    os.environ.pop(_leaked_var, None)

os.environ[PINNED_SESSION_ID_VAR] = TEST_SESSION_ID
os.environ[SKIP_LIVENESS_ENV] = "1"

# Pin XP_AGENTS_DATA to a throwaway dir for the whole test session. With
# SMM_DIR stripped above, any production code that derives its SMM in-process
# (resolve_smm_dir -> _derive_smm_dir -> init.sh, which inherits os.environ)
# would otherwise fall back to a REAL root and litter it with one project-id
# dir per ephemeral test git repo. Redirecting keeps init.sh's per-repo
# derivation semantics but lands everything under temp, cleaned up at
# interpreter exit. Base classes that os.environ.copy() inherit this and then
# override it with their own per-class temp, so this only affects paths that
# don't set XP_AGENTS_DATA themselves.
#
# Pinned on the TOP-preference var, not CLAUDE_PLUGIN_DATA: a pin that anything
# can outrank is not containment, and XP_AGENTS_DATA outranks it by design.
_test_plugin_data = tempfile.mkdtemp(prefix="xp-agents-test-plugin-data-")
os.environ["XP_AGENTS_DATA"] = _test_plugin_data
atexit.register(shutil.rmtree, _test_plugin_data, ignore_errors=True)

# Same redirect, same reason, for the teammate prompt/tee-log namespace. Anything
# that drives a spawn mkdirs `<root>/<project-id>/<sprint-id>/` for real, and the
# project id is derived from a throwaway temp SMM dir — so the suite minted a real
# directory under the real, SHARED /tmp root and nothing removed it (668 stranded
# dirs; ten suites across three base classes still mint one every run).
#
# A redirect, NOT a post-hoc rmtree of the token back out of the shared root: the
# token is derived from whatever SMM dir a test happens to hold, so one leaked
# SMM_DIR turns that sweep into `rm -rf` of a LIVE project's teammate logs. Here
# the writes simply never land in the real root, which is the same containment
# CLAUDE_PLUGIN_DATA gets above and needs no destructive step to hold.
#
# Honors an inherited value so a parent process can aim a child suite at a root it
# can inspect — test_temp_dir_reaping does exactly that to prove spawns really do
# mint namespaces here, rather than passing because nothing was created at all.
_teammate_log_root = os.environ.get("XP_TEAMMATE_LOG_ROOT")
if not _teammate_log_root:
    _teammate_log_root = tempfile.mkdtemp(prefix="xp-agents-test-teammate-logs-")
    atexit.register(shutil.rmtree, _teammate_log_root, ignore_errors=True)
os.environ["XP_TEAMMATE_LOG_ROOT"] = _teammate_log_root
