---
name: xp-scaffold-worktree
description: >-
  Scaffold stack.worktree_bootstrap: measure a fresh worktree's gap for a
  declared command, propose a candidate, verify it closed the gap, refuse
  otherwise.
allowed-tools:
  - Read
  - Grep
  - Glob
  - AskUserQuestion
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(python3 */scripts/worktree_differential.py *)
  - Bash(python3 */smm/system_context_cli.py *)
  - Bash(git rev-parse *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Scaffold Worktree Bootstrap

> **Sequential discipline.** Run Steps 0-8 in order, one step per turn — never
> batch the Step 4 `AskUserQuestion` with the Step 5 verification it authorizes.

Entry point for `/xp-scaffold-worktree`. **Inline — do not fork a subagent.**

A fresh worktree materializes tracked files only, so anything ignored is
absent. `stack.worktree_bootstrap` is the command that closes that gap. This
skill's whole point is that it is **measured, never inferred**: a candidate's
own exit status proves nothing — two plausible candidates were measured against
real repositories, both exited 0, and one fixed nothing at all.

## Step 0: Resolve the checkout root

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
```

Every measurement below carries `--cwd "$REPO_ROOT"` and `--smm-dir "$SMM_DIR"`.

`--cwd` must be the ROOT. Given a subdirectory the tool refuses, because its
two legs would then differ by POSITION as well as by checkout — measured on a
fully committed tree, where no gap is possible, that reads as a gap.

`--smm-dir` is required and does more than parse: it resolves into the shared
environment both legs run under, and the throwaway's declared teardown needs it
to run. Without the flag the tool exits 2 before measuring anything.

## Step 1: Read state

`NONE_DECLARED=true` — stop. There is no command to measure against; ask the
customer to declare `stack.test_command` first.

`WORKTREE_CLEAN=false` — warn before going further. The worktree leg is created
at HEAD while the other runs against the working tree, so a single uncommitted
tracked edit diverges the two on its own and manufactures a gap no bootstrap
could close. Offer to wait until the tree is clean.

`CURRENT_BOOTSTRAP` other than `none` — say what is already declared. A
completed run replaces it.

## Step 2: Detect

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/worktree_differential.py \
    --command "$TEST_COMMAND" --cwd "$REPO_ROOT" --smm-dir "$SMM_DIR"
```

The result is JSON on stdout and the exit status is 0 whenever the tool RAN —
the verdict lives in `outcome`, never in the exit status. Branch on `outcome`
**and** `caveats`, never on `outcome` alone:

- `refused` or `error` — print `reason` verbatim and stop.
- `no_gap` whose `caveats` carries `DEGRADED PLACEMENT` — the measurement is
  **inconclusive**, not clean. The throwaway landed inside the repository, so it
  reaches the primary's installed state by walking up and a real gap reads as
  none. Say so and stop. Never report "nothing to scaffold" from this run.
- `no_gap` with no such caveat — nothing to scaffold. Declare nothing, stop.
- `gap` with `primary_exit` other than 0 — refuse. The declared command does not
  pass where it should, so the divergence cannot be attributed to provisioning.
  Report both exit codes and ask the customer to fix the command first.
- `gap` with `primary_exit` of 0 — continue, printing `caveats` verbatim. Two
  of them are intrinsic to the method: a worktree always sits at a different
  path, and HEAD is not the working tree. Either can produce a gap that no
  provisioning would fix, which is why the next step asks a human.

## Step 3: Propose

Read the repository and propose ONE command that would prepare a fresh
checkout: a setup entry point the project already documents, a target in its
build file, a documented one-liner in its contributor docs. Prefer something
the project already owns over anything assembled here.

Judgment is allowed — reading a repository and recognising its own setup entry
point works whatever it is written in. Inventing per-ecosystem install steps is
not: ignored state splits into the part that is the same in every checkout and
the part that derives from the checkout itself, and only the project knows
which is which.

**Proposing nothing is an allowed outcome.** When the repository documents no
setup entry point, go straight to Step 6 and say so.

## Step 4: Confirm

Ask before measuring, and disclose the cost verbatim rather than summarising
it:

> Verification runs `<candidate> && <declared command>` in **both** the
> throwaway worktree **and your primary checkout**. Its side effects — installs,
> lockfile writes, generated files, anything it starts — land on your real
> working tree, not only on the throwaway.

```
AskUserQuestion(
  question: "<the disclosure above, then: verify this candidate?>",
  options: [
    "Verify it",
    "Edit the candidate first",
    "I'll author it myself",
    "Cancel",
  ]
)
```

**Edit** — take the customer's text as the candidate and re-ask. **Author it
myself** — go to Step 6; an authored command is still unverified until it has
been through Step 5. **Cancel** — exit: _"Cancelled — nothing was declared."_

## Step 5: Verify

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/worktree_differential.py \
    --command "<candidate> && $TEST_COMMAND" --cwd "$REPO_ROOT" \
    --smm-dir "$SMM_DIR"
```

Declare only when **all three** hold. Any one of them alone is fail-open:

1. `outcome` is `no_gap`.
2. `worktree_exit` is 0. `no_gap` means the two exit statuses are IDENTICAL,
   whatever they are — a candidate that breaks the declared command the same
   way in both checkouts also reads `no_gap`.
3. `caveats` carries no `DEGRADED PLACEMENT`. That caveat means the throwaway
   could reach the primary's state, so a candidate that did nothing satisfies
   both conditions above.

Re-measuring is the only thing that separates a working bootstrap from a
plausible one. Do not substitute the candidate's own exit status for it.

## Step 6: Refuse

On every other result — and on a candidate nobody could propose — **declare nothing**.
Name which leg failed, with its exit status and the matching output tail
(`worktree_output` or `primary_output`), then ask the customer to author the
command themselves and re-run this skill to verify it.

An unverified value in this field is worse than an empty one: the empty field
is a known gap, while a wrong command restores exactly the false green this
measurement exists to kill.

## Step 7: Declare

```bash
printf %s '"<the verified command>"' \
  | python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py \
      --smm-dir "$SMM_DIR" edit-stack-field worktree_bootstrap
```

The value is JSON on stdin. `--smm-dir` is GLOBAL and must come before the
subcommand.

Over 100 characters the schema refuses the write. Do not truncate to fit — ask
the customer to move the command into a script the repository owns and declare
the path to that script instead. A command that long is one the project should
be holding in a file.

## Step 8: Report scope honestly

Name the ONE command the bootstrap was verified against.

When `### SURFACES` listed surfaces carrying their own commands, say plainly
that those were **not verified**. A single project can hold both artifacts that
a fresh checkout can reproduce and artifacts it cannot, so a bootstrap proven
for one command is not proven for another — and there is only one field to
declare into. Offer to re-run this skill against another surface's command.
