# Feature Request: Prompt for `Resolves-Event:` trailer when commit matches open concerns

**Plugin:** `xp-agents`
**Component:** Proposed — new hook / skill augmentation. Candidate location: `scripts/bash_post_tool.py` (pre-commit inspection) or `skills/xp-quality-review/SKILL.md` (review-time check).
**Priority:** Medium (4th consecutive retro requesting; sprint-006 shipped 7 unlinked resolutions despite adopted conventions)

---

## Problem

The plugin already supports linking commits to open concerns via the `Resolves-Event:` trailer in the commit body (parsed by `scripts/commits.py:extract_resolves_trailer` → `scripts/bash_post_tool.py:184`). When present, the hook emits a commit event with `metadata.resolves: [<event_id>, …]`, which `resolution.py` consumes to close concerns in the SMM.

The trailer is entirely opt-in. In practice, the authoring agent (main Claude, or a teammate subagent) forgets to emit it, even when a commit clearly addresses a recently-filed concern. The result:

- **Concerns pile up as `unresolved_concerns`** in retro metrics — falsely, because many _were_ resolved; the commit just didn't say so.
- **Retro Keep/Fix analysis misreads the health signal** — a sprint that closed 10 concerns but emitted 7 unlinked commits shows `concerns_resolved: 3, concerns_open: 18` instead of the accurate `concerns_resolved: 10, concerns_open: 11`.
- **The convention gets asked for every retro, adopted every retro, and violated every sprint.** This is the 4th retro in a row this project is raising it. Sprint-006 adopted convention `63598f4ad872` explicitly; sprint-006 then shipped 7 unlinked resolutions.

Mechanical enforcement beats discipline. The tool should _see_ the signal and prompt the author.

---

## Current authoring flow (gap highlighted)

1. Agent writes code, runs tests, commits.
2. `bash_post_tool.py` runs after `git commit`, parses the message, extracts `Resolves-Event:` if present.
3. **Gap:** nothing checks whether the commit _should have_ had a trailer. Open concerns that match the change never get linked.
4. Event emitted to SMM, possibly with empty `metadata.resolves`.
5. Next retro observes high `unresolved_concerns` count, flags "resolver-id bookkeeping regressed," and files another retro Try. Loop.

---

## Proposed mechanism

Add a **pre-commit concern-match probe** that fires between step 2 and step 4 (or earlier — at `/xp-quality-review` or commit gate time):

### Inputs

- `cwd` — the repo
- `committed_files: set[str]` — already known from `commits.get_committed_files()`
- `msg: str` — commit message subject + body
- Open concerns/risks from `shared_mental_model.json` (`type="concern"` or entries in the `risks` pillar with `severity in {"problem", "uncertainty"}`)

### Matching heuristics (any one matches = "possible resolution")

1. **File overlap** — if an open concern's body mentions a path present in `committed_files`, it's a candidate.
   Example: concern says "`device-keys.integration.test.ts` has 44x `as string` casts"; the commit touches that file.
2. **Topic keyword overlap** — split concern body into content words (drop stopwords); if ≥2 content words appear in the commit message, it's a candidate. Case-insensitive. Use a small stopword list; no need for full NLP.
3. **Explicit ID mention** — if the commit message contains a 12-hex event ID that matches an open concern, auto-link it even without a formal `Resolves-Event:` trailer (emit a warning about trailer discipline, but accept the link).

### Output

For each candidate, prompt the authoring agent (via stderr block, hook output, or a new `STOP` signal from the hook) with:

```
xp-agents: this commit may resolve open concern(s):

  - <event_id_1> — <first 80 chars of content>
  - <event_id_2> — <first 80 chars of content>

If correct, re-commit with a trailer:

  git commit --amend --trailer "Resolves-Event: <event_id_1>, <event_id_2>"

If incorrect, proceed — this prompt is advisory and will not block.
```

### Failure-mode analysis

| Scenario                                      | Behavior                                  | Acceptable?                 |
| --------------------------------------------- | ----------------------------------------- | --------------------------- |
| Commit matches concern, trailer present       | No prompt, link emitted                   | ✅                          |
| Commit matches concern, trailer missing       | Prompt shown, agent re-commits            | ✅                          |
| Commit matches concern, agent ignores prompt  | Warning logged to SMM as a `status` event | ✅ (observable at retro)    |
| Commit doesn't match any concern              | No prompt                                 | ✅                          |
| Commit matches wrong concern (false positive) | Prompt shown, agent ignores               | ✅ (advisory, not blocking) |
| Too many candidates (>5)                      | Show top 5 by overlap score               | ✅                          |

No false-blocking. Always advisory. The discipline lift is: the agent now _knows_ a match exists and has a one-line fix.

---

## UX details

### Where the prompt fires

Two candidates, listed in preference order:

1. **Best — `/xp-quality-review` skill**: after the agent runs the review but before it runs `/xp-security-triage`, the skill reads open concerns and emits the prompt. The agent re-reads the commit and chooses to amend or not. This is the natural place because the review skill is already reading the diff and the SMM.
2. **Fallback — `bash_post_tool.py` Bash post-hook**: after `git commit` completes. Requires re-commit via `--amend`, which is uglier but works for teammates that skip `/xp-quality-review`.

Recommend **both**: `/xp-quality-review` catches most cases with a clean amend flow; `bash_post_tool.py` catches the ones where the agent forgot to run review. Hook prompt defers to the review's prompt if it already fired for the same commit hash.

### Prompt framing

Keep the prompt short and factual. No value-judgment language ("you forgot again!"). Show concern ID, truncated content, and exact amend command. Let the author decide. The whole point is to _reduce_ friction on a documented-but-never-followed convention, not to scold.

### Opt-out

Add `xp.resolves-trailer-prompt = "off"` to the plugin config for projects that prefer pure manual linking. Default: `"on"`.

---

## Implementation sketch

Roughly 80-120 lines of Python plus a markdown update to `xp-quality-review/SKILL.md`. Core logic:

```python
# new: scripts/resolves_probe.py
from __future__ import annotations
import re
from pathlib import Path

_STOPWORDS = frozenset({"the", "a", "and", "or", "to", "of", "in", "for", ...})
_ID_RE = re.compile(r"\b[0-9a-f]{12}\b")

def find_candidate_concerns(
    committed_files: set[str],
    msg: str,
    open_concerns: list[dict],
) -> list[tuple[dict, float]]:
    """Return (concern, score) pairs ranked by match strength."""
    candidates: list[tuple[dict, float]] = []
    msg_words = {w for w in re.findall(r"\w+", msg.lower()) if w not in _STOPWORDS}
    mentioned_ids = set(_ID_RE.findall(msg))

    for c in open_concerns:
        score = 0.0
        content = c.get("content", "").lower()
        # File overlap
        for f in committed_files:
            if f in content:
                score += 2.0
        # Keyword overlap
        c_words = set(re.findall(r"\w+", content)) - _STOPWORDS
        overlap = msg_words & c_words
        if len(overlap) >= 2:
            score += len(overlap) * 0.3
        # Direct ID mention
        if c["id"] in mentioned_ids:
            score += 10.0
        if score > 0:
            candidates.append((c, score))

    candidates.sort(key=lambda t: -t[1])
    return candidates[:5]


def format_prompt(candidates: list[tuple[dict, float]]) -> str:
    lines = ["xp-agents: this commit may resolve open concern(s):", ""]
    for c, _score in candidates:
        snippet = c["content"][:80].replace("\n", " ")
        lines.append(f"  - {c['id']} — {snippet}")
    trailer = ", ".join(c["id"] for c, _ in candidates[:3])
    lines += [
        "",
        "If correct, re-commit with:",
        f'  git commit --amend --trailer "Resolves-Event: {trailer}"',
        "",
        "If incorrect, proceed — this is advisory.",
    ]
    return "\n".join(lines)
```

Integration points:

1. Call `find_candidate_concerns` in `bash_post_tool.py` after `extract_resolves_trailer` — skip if `resolves` is already non-empty.
2. If candidates exist and `resolves` is empty, print `format_prompt()` to stderr. The PostToolUse hook surface can return a non-blocking advisory.
3. Also emit a `status` event `resolves_probe_candidates_shown` with the candidate IDs so retros can track how often prompts are shown vs acted on.

---

## Success metric

At retro time, report `resolves_link_rate` per sprint:

```
resolves_link_rate = commits_with_resolves / commits_that_had_candidates
```

When the feature ships, sprint-006's data should look like:

- Before: `resolves_link_rate = 3/10 = 30%` (7 unlinked resolutions)
- After (projected): `resolves_link_rate > 80%` (agent responds to most prompts)

If three consecutive sprints hit ≥80%, the retro can stop asking about it. That's the explicit goal.

---

## Non-goals

- Do NOT auto-inject the trailer without agent confirmation. Silent modification of commit messages violates Honesty — the agent should _see_ the match and decide.
- Do NOT block commits. This is advisory. Blocking on a false positive would be worse than the current state.
- Do NOT retro-link already-emitted commit events. The SMM is append-only; if a past commit missed its trailer, it stays unlinked. Retros handle the cleanup via `force_resolve` in curation.

---

## Related events in this project's SMM

- Convention `63598f4ad872` (adopted sprint-005): "When a commit resolves a recently-deferred concern, include concern_id in commit metadata.resolves OR emit a linking status event."
- Concern `0e0830b10a14` (sprint-006): "sprint-006 shipped 7 resolutions without trailers." Still open — this feature request resolves it.
- Decision `c40762d3edf3` (retro Try `0e0830b10a14` adopted 2026-04-18): main agent committed to writing this feature request.

---

## Author

Filed by SimplyHuman project during sprint-007 kickoff, 2026-04-18. The 4th consecutive retro raising the gap was the prompt — manual convention isn't scaling, mechanical prompting is the next lever. Happy to prototype as a PR if the plugin team accepts the direction.
