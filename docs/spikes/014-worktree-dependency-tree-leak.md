# Spike-014: does teammate worktree placement leak the primary's dependency tree?

Concern `6c689f7e9f96` (found by spike-005 §9), Risk `64b1414e1a67`.

## 1. Question

This plugin places teammate worktrees **inside** the repo at
`{git_root}/.claude/worktrees/worktree-story-NNN`. Module resolution (Node's
`require`/import) walks **up** the directory tree. So does a worktree inside the
repo resolve modules from the **primary checkout's** `node_modules` — at versions
it never installed, changing under it when the primary reinstalls? Spike-005 saw
it once on `legacy2` (`@legacy/shared` resolved only from the primary). This spike
confirms/refutes it, tests whether provisioning masks it, and traces the blast
radius of moving worktrees out.

## 2. Method

- **Synthetic isolation** of Node's resolution algorithm (a minimal fake repo with
  `primary/node_modules/@shared/mod`, a worktree at `primary/.claude/worktrees/…`
  with no local `node_modules`, and a copy outside the repo). Node v22.14.
- **Non-mutating precondition check** on a second real repo (`divineruin`).
- **Code trace** of every consumer of the worktree path prefix.

## 3. Findings

### 3.1 The leak is real (AC1) — confirmed at the mechanism level, not one observation

The synthetic probe requires `@shared/mod` from three positions:

| Position | Result |
|---|---|
| Inside `.claude/worktrees/…`, no local `node_modules` | **Resolves from the PRIMARY's `node_modules`** (`FROM_PRIMARY_NODE_MODULES`) — **LEAK** |
| Outside the repo, no ancestor `node_modules` | `MODULE_NOT_FOUND` — no leak (fails honestly) |
| Inside, WITH its own complete `node_modules` | Resolves the **local** copy (`FROM_LOCAL…`) — masked |

This is Node's documented node_modules walk-up, so it is **repo-independent**, not a
`legacy2` quirk. `divineruin` (second repo) meets every precondition — gitignores
`node_modules`, has a primary `node_modules`, is a `workspaces` monorepo — so a
worktree inside it would leak identically. Confirmed beyond the single legacy2
observation.

### 3.2 Provisioning masks it only if COMPLETE (AC2)

A worktree with its **own complete** `node_modules` resolves the local copy first —
the walk-up stops at the nearest `node_modules`, so the leak is masked. **But** any
module the worktree **fails to install** still walks up to the primary's tree and
resolves silently, at the primary's version. So story-011's bootstrap masks the leak
**only when provisioning is complete**; a partial/failed install leaves the exact
"partial, invisible cross-checkout resolution" hazard spike-005 named — worse than a
clean failure, because it looks green. Bootstrap completeness is therefore
load-bearing under the keep-placement option.

### 3.3 Blast radius of moving worktrees outside the repo (AC3)

Everything keys on one constant: `WORKTREE_PATH_FRAGMENT = ".claude/worktrees/"`
(`scripts/identity.py:20`, re-exported by `scripts/worktree.py:31`).

| Consumer | File | Effect of moving outside |
|---|---|---|
| `is_worktree_teammate` — detection marker `/.claude/worktrees/` | `identity.py` | **MUST update** the marker; the interface_contract's load-bearing constraint (detection must not break) |
| `worktree_path` — `{git_root}/{fragment}{name}` | `worktree.py:66` | Rebase to an out-of-root base (not `git_root`-relative) |
| worktree enumeration / prune / cleanup — `worktree-story-` prefix | `worktree.py`, `cleanup_teammate.py` | Follow the fragment change; the `worktree-` name prefix is unaffected |
| goal/gate scoping — `worktree-story-*` | `session_start.py`, `lead_gates.py` | Key on the name prefix, not the path — unaffected |
| `.gitignore` entry `.claude/worktrees/` | repo `.gitignore` | Becomes **moot** (outside the repo → nothing to ignore) |

## 4. Decision (AC4)

**Move teammate worktrees outside the repo, to
`${CLAUDE_PLUGIN_DATA}/{project-id}/worktrees/{name}`** — parallel to where the
plugin already keeps per-project state (SMM at `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/`).

Why this location:
- **Outside every repo** → no `node_modules` ancestry → the leak becomes an honest
  `MODULE_NOT_FOUND` (§3.1), the only option that eliminates it at the root rather
  than masking it.
- **Project-namespaced** by the same id hash as SMM → no cross-project collision.
- **Architecturally consistent** — co-located with the plugin's existing per-project
  state; `git worktree add <abs-path>` works anywhere (the worktree's `.git` points
  back to the main repo).

Rejected alternatives: **keep + mask-via-bootstrap** leaves the partial-install
residual (§3.2); **OS temp** risks a temp-reaper deleting a live worktree; a **sibling
dir** clutters the parent and isn't cleanly project-isolated.

### Caveats carried to the implementation

- `is_worktree_teammate`'s detection marker changes from `/.claude/worktrees/` to the
  new fragment — the load-bearing constraint; the change must keep teammate detection
  working (interface_contract).
- Leans on `CLAUDE_PLUGIN_DATA` resolution, which has a known platform-availability
  caveat (`project_investigation_items`); the implementation must degrade safely if
  it is unavailable.
- The leak concern `6c689f7e9f96` and Risk `64b1414e1a67` stay **open** until the move
  lands — this spike produces the decision, not the fix.

**Follow-on:** a story to change `WORKTREE_PATH_FRAGMENT` + `worktree_path` base +
`is_worktree_teammate` detection to the out-of-repo location, verified by the synthetic
probe shape (inside-old-path leaks; new-location `MODULE_NOT_FOUND`).
