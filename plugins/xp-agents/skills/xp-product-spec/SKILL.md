---
name: xp-product-spec
description: >-
  Create or refine product_spec.md — conversation-driven requirements
  gathering with structured feature tracking. Use when starting a new
  project or adding features to an existing spec.
effort: medium
allowed-tools:
  - Read
  - AskUserQuestion
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Product Spec

The preload above shows the current state: existing spec with feature counts, or "create mode" if no spec exists.

## Mode Detection

- **Create mode** (preload says "No product spec found"): Follow the Create flow below.
- **Update mode** (preload shows existing spec): Follow the Update flow below.

## Create Flow

Guide the user through requirements gathering. Use `AskUserQuestion` to keep it interactive and respect their time.

1. **Project name and overview**: Ask what the product does and who it's for. Keep the overview to 2-3 sentences that capture the core value proposition and target audience.
2. **Features**: Ask for the key features or capabilities. For each feature:
   - Give it a clear, descriptive name (e.g., "User Authentication", not "Auth")
   - Gather 2-5 concrete requirements as bullet points
   - Each requirement should be specific and testable (e.g., "Login with email and password" not "User can log in")
   - Keep asking "Any more features?" until the user says done
   - If the user gives a high-level list, drill into each one for requirements
3. **Technical constraints**: Ask about technology choices, platform requirements, integration constraints, or performance targets. Skip if the user says none.
4. **Non-functional requirements**: Ask about security, accessibility, scalability, or other quality attributes. Skip if none.

Assemble the spec in this exact format:

```markdown
# Product Spec: <Project Name>

## Overview
<2-3 sentence description>

## Features

### <Feature Name> [planned]
- <Requirement 1>
- <Requirement 2>

## Technical Constraints
- <Constraint 1>

## Non-Functional Requirements
- <NFR 1>
```

Write the file:
```bash
cat <<'SPECEOF' | python3 ${CLAUDE_SKILL_DIR}/scripts/save_product_spec.py --smm-dir <SMM_DIR>
<assembled markdown>
SPECEOF
```

Record a status event:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" \
  --agent "xp-product-spec" \
  --content "Created product_spec.md with N features" \
  --working-on '["product_spec.md"]'
```

## Update Flow

1. Show the user a summary of the existing spec (feature counts already in preload output).
2. Ask what they want to do using `AskUserQuestion` with options: "Add features", "Refine existing features", "Add constraints/NFRs", "Done".
3. For new features: gather requirements the same way as Create flow. Add as `### Feature Name [planned]` after existing features.
4. For refinements: read the current spec with `Read`, show the feature to the user, let them add/remove/edit requirements. Only modify `[planned]` features.
5. **NEVER modify `[delivered: ...]` markers** — only `/xp-sprint-review` does that. If the user asks to change a delivered feature, explain that delivered features are locked and suggest adding a new `[planned]` feature instead.
6. Write the full updated spec using `save_product_spec.py` (same pipe pattern as create flow). The writer replaces the entire file, so always include all existing content.
7. Record a status event describing what changed.

## Document Ingestion

If the user provides a file path or pastes document content:
1. Use `Read` to load the file if a path is given.
2. Extract features and requirements from the document.
3. Present the extracted features to the user for confirmation before adding.
4. Add confirmed features as `[planned]` entries.

## Source References

When bootstrapping from existing project documentation, include a `Sources:` line for each feature pointing back to the original docs. This helps agents find detailed design context during sprint planning.

```markdown
### Combat System [planned]
- Phase-based simultaneous declaration
- 500ms collection buffer for batching
- **Sources:** docs/COMBAT_DESIGN.md, docs/GAME_MECHANICS.md §Combat
```

- List the file path(s) where detailed design for that feature lives.
- Use `§Section` notation when the relevant content is in a specific section of a larger doc.
- Only include references that add value — skip if the feature was described entirely by the user with no backing docs.

## Guidelines

- Be concise — gather requirements efficiently, don't over-ask.
- Batch related questions when possible using `AskUserQuestion` with multiple options.
- Every new feature gets `[planned]` status. No exceptions.
- Omit empty sections (if no constraints, don't include "Technical Constraints").
- The spec is a living document — it's OK to start small and add features later.
- Feature names should be descriptive and unique within the spec.
- Requirements should be specific enough for a developer to implement and test.
- When updating, always preserve the full document structure and all existing content.
