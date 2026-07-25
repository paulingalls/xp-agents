# Changelog

History prior to v5.0 lives in [`changelog_pre_v5.md`](changelog_pre_v5.md).

## v5.0.0 — The SMM moves out of the deletable directory

**Major, and the break is worth stating plainly before the reason: the SMM's
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
