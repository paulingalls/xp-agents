# Changelog

History prior to v5.0 lives in [`changelog_pre_v5.md`](changelog_pre_v5.md).

## v5.0.0 — The SMM moves out of the deletable directory

**Two breaking changes ship in this release: the SMM's default location, and
the branch namespace.** The location is the headline and is covered first; the
namespace flip is under "The recorded branch namespace is now the one in force"
below, and it is the one that can change your branch names on upgrade.

### The SMM's default location

**The break is worth stating plainly before the reason: the SMM's
default location changes, and `CLAUDE_PLUGIN_DATA` no longer chooses it.** Two
contracts change. Anyone who exported `CLAUDE_PLUGIN_DATA` to place the SMM must
switch to `XP_AGENTS_DATA`; that variable is still read, but only to *find* an
SMM that already exists, never to decide where one goes. And any tooling that
reads `~/.claude/plugins/data/…/smm/` directly keeps working against a tree that
is no longer the live one once relocation has run — a stale read, not an error.
Relocation itself is automatic and by copy, so for most users nothing is asked of
them; the major number reflects the contract break, not the difficulty.

The Claude plugins reference says
`${CLAUDE_PLUGIN_DATA}` — `~/.claude/plugins/data/{id}/` — "is deleted
automatically when you uninstall the plugin from the last scope where it is
installed," and the CLI deletes by default (`--keep-data` opts out). That is
where the SMM has lived: `events.jsonl`, `sprint.json`, `execution_plan.json`,
`system_context.json`, `session_history.json` and every retrospective. Code is in
git; a project's *memory* is not. It survives plugin updates but not an
uninstall — including the common uninstall-then-reinstall — and it fails
silently: the plugin keeps working, the next session just starts from a seed
retrospective as though the project were new.

New SMMs now go to `${XP_AGENTS_DATA:-~/.xp-agents/data}/{project-id}/smm/`,
which no plugin lifecycle operation touches.

**An existing SMM is relocated for you, by COPY.** On the first resolution after
upgrade, an SMM found under a plugin-data root is copied to the new root and used
from there. The source is never deleted — an interrupted or wrong relocation
therefore loses nothing, and every failure path falls back to reading the old
tree. Once you are satisfied, the old directory is yours to delete.

Discovery checks a LIST of legacy roots (`$CLAUDE_PLUGIN_DATA` when set, then the
marketplace and dev-mode defaults), because that variable is absent in some hook
processes and a dev-mode install resolves the plugin id differently; a single
candidate would let a process that cannot see the real root mint an empty
directory that then permanently reads as authoritative.

**Relocation is declined, never forced, while any teammate is live.** A teammate
has its SMM directory pinned to an absolute path when it is spawned and cannot be
redirected, so moving the SMM out from under one splits the event log with no
merge path — and because the plugin cache is versioned, a mid-session plugin
update leaves old and new code running side by side, which is exactly when this
would bite. Both kinds are checked: worktree teammates by their directory, and
in-place teammates by their marker files. While one is live the old location keeps
being used, and relocation happens on a later session. A `.migrated-to` pointer is
left behind so a process pinned to the old path just before a relocation is
redirected rather than writing where nothing reads.

**And when relocation stays declined, the session says so.** The liveness gate
keys on a worktree *directory* existing, and nothing removes one whose branch
never merged — cleanup refuses on an unmerged branch, by design. So a single
abandoned story can hold the gate on indefinitely. A one-line SessionStart notice
now names the risk and the blocker whenever the resolved SMM is still under a
host-managed root. It is a notice, never a gate, and it is a positive test
against the at-risk roots: point `XP_AGENTS_DATA` or `SMM_DIR` wherever you like
and nothing nags you.

**`scripts/migrate_smm_root.py` is the manual half.** Run it with no arguments
and it reports where the SMM is, where it would go, how big it is, whether the
root is at risk, and — the part the notice cannot carry — exactly which worktree
directories and in-place markers are holding relocation back. `--confirm`
relocates; `--confirm --force` relocates past a signal you have judged stale,
which is the one call automation must not make for you. It does not implement
relocation: copying, locking, the whole-tree re-sync and the forward pointer stay
in `init.sh`, and the tool drives them, so there is no second set of races to
get wrong. After a relocation it compares both trees and tells you where the old
copy still is. Only `smm/` moves — a forced relocation names the sibling worktree
directories it just cut loose, because worktree placement is derived from the
SMM's parent and `/xp-story-close` will no longer find them.

`CLAUDE_PLUGIN_DATA` is now READ for discovery but never chosen for a new SMM.
The harness always sets it, so honoring it as a preference would leave every SMM
in the deletable directory and make this change a no-op.

**If you want the SMM somewhere specific, export `XP_AGENTS_DATA`.** It outranks
everything except an explicit `$SMM_DIR` (which is how a teammate spawner
propagates the lead's SMM across a process boundary).

Also fixed while the root became user-controllable: `init.sh` used to `chmod 700`
the derived root unconditionally, which was harmless when that root was always
plugin-owned but would have narrowed the mode of `$HOME` for anyone setting
`XP_AGENTS_DATA=$HOME`. It now narrows only a root it created. The SMM directory
itself is still always `700`.

### The recorded branch namespace is now the one in force

**The second break: branch names can change on upgrade.**
`branching_strategy.user_namespace` was inert. `identity.user_namespace()`
derived the branch prefix from the git `user.email` local-part and never read the
recorded field, so `system_context.json` could say `alice` while every branch was
cut as `a-smith/...` — with nothing reporting the disagreement. This repo hit
exactly that: the analyzer recorded the prefix already on 200+ merged branches,
the git email had since changed, and the next branch was cut under the new one.

The recorded value now WINS, falling back to git identity when absent or
unusable. It is user-editable via `system_context_cli edit-branching-field`, so
it was always meant as an override; an override nothing reads is a lie.

**What changes for you on upgrade.** If your recorded `user_namespace` disagrees
with your git-derived slug, NEW branches switch to the recorded prefix. Your
existing ones stay visible: `list_user_branches` — which backs kickoff's
orphan-branch triage and free-close discovery — searches both the recorded
namespace and the git-derived one, so nothing cut before the upgrade drops out
of those listings. What it does not do is RESUME across the change: restarting
work with the same slug cuts a fresh branch under the new prefix rather than
picking up the old-prefix one, which is then an orphan the triage will offer
you. If you would rather not have the switch at all, check
`branching_strategy.user_namespace` in your rendered system context BEFORE
upgrading and either edit it to the prefix you actually use or delete the field
to keep deriving from git.

The field is also now validated as a git ref segment, at the same two points
`integration_branch` already was: rejected at write time (`user_namespace_error`),
healed to "no override" at use time (`healed_user_namespace`). It reaches `git
branch` and `git checkout` as argv, so a leading dash would have arrived as a
FLAG.

This landed as v4.19.0 on the branch that became this release. There was no
separate v4.19.0 release, so the entry under that heading in
[`changelog_pre_v5.md`](changelog_pre_v5.md) is a mid-branch snapshot, not a
shipped version — where the two disagree (it predates the dual-namespace
search), this note is the accurate one.
