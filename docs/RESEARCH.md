# Research & Competitive Landscape

## Existing Approaches

| Project | Author | Approach | Strength | Gap |
|---|---|---|---|---|
| **The Ring** | Lerian Studio | 83 skills, 37 agents, 6 plugins, multi-platform | Comprehensive engineering practices. Multi-platform (Claude, Cursor, Cline, Factory AI). | No inter-agent communication. Skills are individual behaviors, not team coordination. |
| **Swarm Tools** | Joel Hooks | Event-sourced engine (libSQL + Hive + Hivemind + SwarmMail) | Append-only event log. File reservations. Learning system (patterns mature over time). 122 releases, 971 commits. | Requires Bun + npm. Heavyweight. Task decomposition focus, not team communication. No XP values. |
| **Gas Town** | Steve Yegge | Workspace manager for 20-30+ agents | Battle-tested at scale. Crash recovery. GUPP principle. | Orchestrator-centric. No structured semantic communication. |
| **Beads** | Steve Yegge | Markdown-based agent memory | Simple, git-backed. Inspired Anthropic's task system. | Memory, not communication. No event semantics or conflict detection. |
| **MCP Agent Mail** | Jeffrey Emanuel | Mail-like messaging via MCP server | Agent identities, file leases, Git+SQLite persistence, web UI. | Point-to-point messaging. Requires HTTP server. No shared mental model. |
| **Nemp Memory** | Sukin Shetty | Shared local memory store (`.nemp/memories.json`) | Proved parallel sub-agents sharing memory works. | Unstructured JSON. No event types or conflict detection. |
| **Ruflo (Claude Flow)** | Reuven Cohen | Enterprise multi-agent platform (54+ agents) | Q-learning router, swarm coordination. | Very heavyweight. Not a plugin — a platform. |
| **Claude Code Agent Teams** | Anthropic | Built-in (tmux + filesystem mailboxes + task lists) | Official, zero setup. | Point-to-point messaging. No shared mental model. Acknowledged limitations. |

## Where xp-agents Fits

```
                    Individual Agent          Team Coordination
                    Behavior                  Protocol
                    ─────────────             ─────────────
Lightweight         The Ring (skills)         xp-agents ← HERE
(zero-dep plugin)   Beads (memory)
                    Nemp Memory

Heavyweight         —                        Swarm Tools (event-sourced)
(requires install)                           Gas Town (orchestrator)
                                             Ruflo (platform)
                                             MCP Agent Mail (HTTP server)
```

**No existing project combines all three of:**
1. Structured semantic communication (typed events with sync semantics)
2. XP values and practices as the coordination philosophy
3. Zero-dependency plugin (Python stdlib only)

---

## Lessons from the Landscape

### What We Adopted

**1. Append-only event logs** (from Swarm Tools)

Swarm Tools' 122 releases validate our core architectural bet. Their event store uses typed events (`agent_registered`, `message_sent`, `file_reserved`, `file_released`, `checkpoint`, `outcome`) with different semantics — confirming that event type granularity matters.

*→ Reflected in: Core architecture, Milestones 1 & 2*

**2. File reservation signaling** (from Swarm Tools & MCP Agent Mail)

Both implement file reservation — agents declare intent before modifying files. Swarm Tools uses `DurableLock` with CAS-based exclusion; MCP Agent Mail uses advisory leases with TTL expiry.

*Our approach*: Lighter — `status` events include a `working_on` field for intent signaling without full locking.

*→ Reflected in: Milestone 1 (schema), Milestone 5 (skills), Milestone 8 (CLAUDE.md)*

**3. GUPP: Physics over politeness** (from Gas Town)

Yegge's most powerful insight: agents that restart should immediately check for pending work and resume, without waiting for permission. *"If there is work on your hook, YOU MUST RUN IT."* The biggest failure isn't wrong work — it's idle agents too polite to start.

*→ Reflected in: Milestone 3 (SessionStart hook), Milestone 5 (skills), Milestone 8 (CLAUDE.md GUPP Rule)*

**4. Crash recovery through persistent state** (from Gas Town & Beads)

Yegge's key insight: *"If your state is in git, it's automatically versioned, distributed, and recoverable."* Gas Town achieves "Nondeterministic Idempotence" — workflows survive crashes because state is persistent, not in the context window.

*Our approach*: File-based log that survives compaction and crashes. Materializer uses atomic writes via `tempfile` + `os.rename()`.

*→ Reflected in: Milestone 1 (init.sh crash-safe), Milestone 2 (materialize.py atomic writes)*

**5. Structured skill discovery** (from The Ring)

The Ring's `ring:using-ring` meta-skill auto-generates a quick reference from skill frontmatter before any action, preventing agents from forgetting capabilities.

*Our approach*: Skills use structured frontmatter with `trigger` and `skip_when` conditions. SessionStart hook lists available skills.

*→ Reflected in: Milestone 3 (SessionStart lists skills), Milestone 5 (all skills have frontmatter)*

**6. Schema extensibility for learning** (from Swarm Tools)

Swarm Tools records outcomes for every task — duration, errors, files touched — and matures patterns: `candidate → established → proven`. Anti-patterns auto-generate at 60% failure rate.

*Our approach*: All events include an optional `metadata` object for future analytics without schema migration. `schema_version` field enables evolution.

*→ Reflected in: Milestone 1 (schema extensible `metadata` + `schema_version`), Milestone 10 (migration utility)*

**7. Marketplace plugin structure** (from The Ring & Swarm Tools)

Both distribute as Claude Code plugin marketplaces. The Ring manages 6 plugins with versioning. Validates our marketplace-first decision.

*→ Reflected in: Distribution section, Milestone 9*

### What We Avoid

**1. External runtimes.** Swarm Tools needs Bun/npm. Gas Town needs Go+Dolt+tmux. MCP Agent Mail needs Python 3.14+uv+HTTP. Each dependency is a failure point. Yegge warns: *"Gas Town is expensive as hell."* Our zero-dep approach is our strongest advantage.

**2. Building an orchestrator.** Gas Town is Yegge's *fourth* orchestrator. It's complex enough that he warns users away unless they "juggle at least five Claude Codes daily." We provide a communication substrate, not session management.

**3. Point-to-point messaging.** MCP Agent Mail and Agent Teams both use mailboxes — the exact architectural problem we solve. The SMM's broadcast-by-default model is fundamentally more efficient.

**4. Conflating memory with communication.** Beads is memory. Nemp Memory is memory. The SMM is a communication protocol with memory properties — its primary purpose is coordination, not storage.

**5. The "Dementia Problem."** Yegge's vivid insight: agents create recursive plans they forget about. *"By phase 3, the AI has mostly forgotten where it came from. It declares, 'Oh wow, this is a big project, I'm going to break it into five phases.'"* Our `decision` and `convention` events survive compaction and prevent this.

**6. Over-engineering review.** The Ring has 7 parallel reviewers and 83 skills. Our 4 focused subagents with XP values cover more ground — the courage-reviewer can say *anything* that needs saying, not siloed into a narrow category. And anyone can extend the team by copying `agents/_template.md` and adding SMM interactions — turning any subagent into a full team member.

---

## Research Sources

| Source | Title | Date | Key Contribution |
|---|---|---|---|
| Galileo Labs (Pratik Bhavsar) | "Why Do Multi-Agent Systems Fail Even When Agents Work Perfectly in Isolation?" | Feb 2026 | 7 production failure modes, coordination cost scaling |
| Daniel Bentes | "Five AI Agents Walk Into a Group Chat" | Feb 2026 | Group dynamics failures from game theory and distributed systems |
| Lou, Lu, Raghu, Zhang (USC/ASU) | "Visioning Human–Agentic AI Teaming" | Mar 2026 | Team SA theory; shared mental models as primary alignment mechanism |
| Zhang et al. (Nature) | "LLM tools as catalysts for collective cognition" | Feb 2026 | LLM collective cognition limits; over-reliance risks |
| Gergely Orosz (Pragmatic Engineer) | "The Future of Software Engineering with AI: Six Predictions" | Feb 2026 | XP practices resurgence in AI era |
| Anthropic | Claude Code Agent Teams documentation | 2026 | Official architecture, limitations, best practices |
| Carraro, Furlan, Netland | "How shared mental models drive proactive problem-solving" (Human Relations) | 2025 | SMM empirical evidence for team coordination |
