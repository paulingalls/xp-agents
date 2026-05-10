# Sister-Test Discovery Design

**Status:** Design (sprint-080 story-001 SPIKE) — no code lands here.
**Implementation milestone:** TBD.
**Supersedes:** the deferred wiring shipped on `paulingalls/story-001-sister-test-validator` (commit `4395af5a`, sprint-079 story-001).

The plugin is project-generic (constraint `f7920cf86da0`). Sister-test auto-inclusion must work for any plugin user — Python, Go, JavaScript/TypeScript, Rust — not only this repo.

**TL;DR for implementers.** New top-level `test_layout` field in `system_context.json` (§3, recommendation). Pure function `discover_sister_tests(source_path, layout, project_root) -> list[str]` (§4). Built-in convention bundles for Python/Go/JS/Rust (§2). Wire three `sprint_cli.py` subcommands through `save_sprint.run()` (§5).

---

## 1. Current state and what's wrong

### 1a. The validator that shipped on the deferred branch

Commit `4395af5a` added two helpers to `plugins/xp-agents/skills/xp-sprint-start/scripts/save_sprint.py`. Quoting verbatim from that branch:

```python
def _sister_test_stem(source_path: str) -> str | None:
    """Return the test-name stem to glob for, or None if no rule matches.

    - `*/scripts/<x>.py`         → `<x>` (basename without `.py`)
    - `skills/<name>/preload.sh` → `<name>` with `xp-` stripped, dashes→`_`
    """
    p = PurePosixPath(source_path)
    parts = p.parts
    if len(parts) >= 2 and parts[-2] == "scripts" and p.suffix == ".py":
        return p.stem
    if len(parts) >= 2 and parts[-1] == "preload.sh" and "skills" in parts:
        idx = parts.index("skills")
        if idx + 1 < len(parts) - 1:
            return parts[idx + 1].removeprefix("xp-").replace("-", "_")
    return None


def _find_sister_tests(source_path: str, project_root: Path) -> list[str]:
    stem = _sister_test_stem(source_path)
    if stem is None:
        return []
    matches = sorted(project_root.glob(f"tests/**/test_{stem}*.py"))
    return [m.relative_to(project_root).as_posix() for m in matches]
```

Three things are baked into this code:

1. **A Python-pytest layout assumption** — the glob `tests/**/test_<stem>*.py` only matches one repository's choices: a top-level `tests/` directory and `test_<x>.py` filename convention. A Go repo with `foo.go` ↔ `foo_test.go` siblings, or a JS repo with `__tests__/foo.test.ts`, sees zero matches and silently no-ops.
2. **Two source-path heuristics specific to this plugin's directory layout** — `*/scripts/*.py` and `skills/<name>/preload.sh` are the two filing patterns *this* repo uses. They have nothing to do with how a typical Python project, much less a Go or JS project, organizes source.
3. **One filename-mangling rule specific to this plugin's naming conventions** — `xp-` prefix strip and dash→underscore is how *this* repo translates skill directory names (`xp-sprint-start`) into Python test stems (`sprint_start`). No other project does this.

Even sprint-079 acknowledged this in CHANGELOG.md (line 26): *"implementation baked in xp-agents-repo conventions … needs redesign with `system_context.json`-driven project-generic source→test mapping so the validator works for any plugin user, not only this repo."*

### 1b. The wiring also shipped DEAD

`save_sprint.run()` is never called by the production skill flows. Three sprint-mutating CLI subcommands in `plugins/xp-agents/smm/sprint_cli.py` go directly to `sprint_store`, bypassing `run()` and therefore bypassing the validator entirely:

- `_cmd_create` (line 157) calls `store.save_sprint(args.smm_dir, data)` (line 165)
- `_cmd_add_story` (line 172) calls `store.save_sprint(args.smm_dir, sprint)` (line 185)
- `_cmd_edit_story` (line 219) calls `store.edit_story(args.smm_dir, args.story_id, updates)` (line 227)

All three skill flows that mutate sprint state — `xp-sprint-start` Step 6, `xp-work-selection` (deferred-story carry), `xp-accept` (story-status edits) — drive `sprint_cli.py`, not `save_sprint.py`. The validator was placed on a branch of the call graph that nothing calls.

### 1c. Why "just wire the existing validator into more callers" is the wrong fix

The minimal fix that comes to mind — make the three CLI subcommands call `save_sprint.run()` — closes the dead-code gap but spreads a project-baked-in heuristic across every plugin user's sprint-write path. The validator would silently no-op on every non-Python project (because none of its rules match), but it would *load and run* on every sprint mutation, giving a false sense that "sister-test discovery is done." Worst case: someone files a bug report when their Go project's `*_test.go` files don't get auto-included, and the maintainer has to explain that the feature was never designed for them.

The right fix needs both: (a) a project-generic discovery mechanism driven by `system_context.json`, and (b) the wiring that routes all three subcommands through whatever wrapper hosts that mechanism. (a) without (b) ships dead. (b) without (a) ships wrong.

---

## 2. Convention strategies

A "test layout convention" is the package of rules that lets the validator answer one question: *for source file X, what existing files on disk are its sister tests?* Each convention has three parts: a **marker** (a file or set of files whose presence in the project root signals the convention applies), one or more **source→test mapping rules** (each: a source-path pattern + how to derive the stem + a test-path glob template), and known **edge cases** the implementation must handle without crashing.

The four conventions below cover the bulk of plugin users today. The implementation should ship them as a built-in table; customers extend or override via `system_context.json` (see §3). Conventions outside these four (Ruby/RSpec, Java/JUnit, Kotlin, .NET/xUnit, Elixir/ExUnit, Swift/XCTest, PHP/PHPUnit) are customer-declarable via `test_layout.overrides` until enough demand emerges to add a built-in bundle. This is intentional — see §6 decision D1.

### 2a. Python (pytest)

- **Marker (any of):** `pytest.ini`, `pyproject.toml` containing a `[tool.pytest.ini_options]` table, `setup.cfg` containing a `[tool:pytest]` section, or `tox.ini` with a `[pytest]` section.
- **Mapping rules:**
  - **R1 — top-level tests/ tree:** `**/<x>.py` → `tests/**/test_<x>*.py`. The trailing `*` matches both `test_foo.py` (exact) and `test_foo_<scenario>.py` (split-by-scenario), the two patterns the pytest community uses interchangeably.
  - **R2 — adjacent tests directory:** `<dir>/<x>.py` → `<dir>/tests/test_<x>*.py`. Common in monorepos where each package owns its own tests folder.
- **Worked example.** Source `src/myapp/auth/login.py` resolves under R1 to existing matches `tests/auth/test_login.py`, `tests/auth/test_login_oauth.py`. Both append to the story's `file_domain` if the story already declares `src/myapp/auth/login.py`.
- **Edge cases:**
  - `conftest.py` is shared infrastructure, not a sister test — never auto-included even when the glob matches it (filename excluded by name).
  - `__init__.py` files in `src/` have no semantically meaningful sister test (an empty package init); skip when stem is `__init__`.
  - A story may declare two source files that share a sister test (`src/foo/a.py` and `src/foo/b.py` both globbed `tests/test_*.py` widely). Dedup at append time.

### 2b. Go (built-in `testing` package)

- **Marker:** `go.mod` at project root.
- **Mapping rule:**
  - **R1 — sibling test file:** `<dir>/<x>.go` → `<dir>/<x>_test.go`. Go's testing tool requires the test file to live in the same package directory as the source; there is no "tests/" tree in the conventional Go layout.
- **Worked example.** Source `internal/auth/login.go` resolves to `internal/auth/login_test.go`. (One test file per source file, by convention; one match expected.)
- **Edge cases:**
  - Files ending in `_test.go` are tests themselves — never re-resolve them (skip when source path matches `*_test.go`).
  - Generated files (`*.pb.go`, `*_gen.go`) commonly have no test sibling; the rule globs but legitimately returns empty. This is fine.
  - `cmd/<binary>/main.go` typically has integration tests under `<repo>/integration/` rather than a sibling `main_test.go`. Out of scope for R1; the customer can declare an override.
  - Internal black-box tests live in package `<x>_test` but still in `<dir>/<x>_test.go` — same filename, different declared package. No special handling needed because filename is what we glob.

### 2c. JavaScript / TypeScript (Jest, Vitest, or framework-native)

- **Marker (any of):** `package.json` containing `"jest"` or `"vitest"` in `dependencies`/`devDependencies`, or a sibling `jest.config.{js,ts,mjs,cjs}` / `vitest.config.{js,ts}`. Next.js and Remix projects typically also have one of the above; the marker key is the test runner, not the framework.
- **Mapping rules (both common, project chooses one):**
  - **R1 — sibling .test file:** `<dir>/<x>.{js,jsx,ts,tsx}` → `<dir>/<x>.test.{js,jsx,ts,tsx}` (and `.spec.` as a co-equal variant). Most common in modern projects.
  - **R2 — `__tests__` directory:** `<dir>/<x>.{js,jsx,ts,tsx}` → `<dir>/__tests__/<x>.test.{js,jsx,ts,tsx}`. Older Jest convention, still widespread.
- **Worked example (worked in detail because the brief calls for a non-Python repo).** A Next.js app with the following layout:

  ```
  package.json     ← contains "jest" in devDependencies
  app/
    auth/
      login.ts                ← story declares this
      login.test.ts           ← R1 match (existing)
      __tests__/
        login.test.ts         ← R2 match (existing)
  ```

  When the planner writes a story with `file_domain: ["app/auth/login.ts — auth controller"]`, the validator runs R1 against `app/auth/login.ts` → finds `app/auth/login.test.ts`; runs R2 → finds `app/auth/__tests__/login.test.ts`. Both append to `file_domain`. Final `file_domain`:

  ```json
  [
    "app/auth/login.ts — auth controller",
    "app/auth/login.test.ts — sister test for app/auth/login.ts",
    "app/auth/__tests__/login.test.ts — sister test for app/auth/login.ts"
  ]
  ```

- **Edge cases:**
  - `.d.ts` declaration files have no runtime test counterpart; skip when source path ends `.d.ts`.
  - `index.ts` re-export files commonly have no test; rule globs and returns empty — fine.
  - TypeScript projects with `.tsx` and `.ts` paired tests (`Component.tsx` ↔ `Component.test.ts`, mismatched extension): the implementation should glob the test pattern with all four extensions, not require an exact extension match.
  - Some teams put tests in a parallel `tests/` mirror tree (`tests/auth/login.test.ts`). This is a third common variant; the customer can declare it as an override. The built-in convention bundles R1 + R2 only.

### 2d. Rust (Cargo + built-in test attribute)

- **Marker:** `Cargo.toml` at project root (or in any workspace member directory).
- **Mapping rule (degenerate for unit tests, real for integration tests):**
  - **R1 — integration tests:** `src/bin/<x>.rs` and `src/lib.rs` → `tests/<x>.rs`. The Cargo convention is one integration-test file per binary or library, living in the top-level `tests/` directory. No glob — exact path match.
  - **No rule for unit tests.** Rust's idiomatic unit tests live *inside* the source file inside a `#[cfg(test)] mod tests { … }` block — there is no sister file to discover. The validator must recognize this and report nothing (not crash, not warn).
- **Worked example.** Source `src/bin/server.rs` → `tests/server.rs` (if it exists). Source `src/auth/login.rs` (a library module, not a binary) → no rule applies, no sister file exists; nothing appended.
- **Edge cases:**
  - Workspace projects (`[workspace] members = [...]` in root `Cargo.toml`) have a `Cargo.toml` per member; the marker triggers per directory and rules resolve relative to the member's root. Implementation either treats each workspace member as its own project root, or extends the rule to support the workspace prefix. Customer-declarable.
  - Doc tests (in `///` comments) have no sister file; ignored by R1.
  - The plan reviewer may want to enforce a complementary check ("source declared but contains no `#[cfg(test)]` block AND no integration sister exists"); that's a future linter, not this validator's job.

---

## 3. `system_context.json` surface

The validator needs to know *which convention this project uses* before it can run. That signal lives in `system_context.json`.

**Recommendation: Option A** (new top-level `test_layout` field). Two designs are credible; the plan reviewer's assumption (event `dced5f9fa635`) flagged that Option B is not obviously worse. Both are presented in §3a-§3c; the recommendation reasoning is in §3d.

### 3a. Option A — new `test_layout` top-level field

```json
{
  "...": "...other system_context fields...",
  "test_layout": {
    "convention": "python_pytest",
    "overrides": []
  }
}
```

`xp-system-context` auto-detects `convention` by probing for the marker files in §2. The customer can edit via a new `edit-test-layout` CLI subcommand. `overrides` is an optional list of `TestLayoutRule` records (see §4) that supplement or replace built-in rules for projects that mix conventions or use unusual filings.

### 3b. Option B — extend `acceptance_surfaces`

The existing `acceptance_surfaces` schema (precedent: `system_context_schema.py:283-319`) already carries `name`, `signals`, `status`, and optional `harness`. A "unit_tests" surface entry could host the convention reference:

```json
{
  "acceptance_surfaces": [
    { "name": "Web App", "signals": ["Next.js in package.json"], "status": "covered" },
    {
      "name": "unit_tests",
      "signals": ["jest in devDependencies"],
      "status": "covered",
      "harness": "jest",
      "test_layout_convention": "js_jest"
    }
  ]
}
```

This reuses `add-acceptance-surface` / `edit-acceptance-surfaces` CLI machinery and the existing validator entry point. No new top-level field, no new schema validator function, fewer lines of code in `system_context_schema.py` and `system_context_cli.py`.

### 3c. Honest comparison

| Dimension | Option A (`test_layout`) | Option B (`acceptance_surfaces` extension) |
|---|---|---|
| Schema additions | New top-level field + new validator function | One new optional field (`test_layout_convention`) on existing entry |
| CLI additions | New `edit-test-layout` / `get-test-layout` subcommands | Reuse `edit-acceptance-surfaces` + `add-acceptance-surface` |
| Validator call-site lookup | Direct: `system_context["test_layout"]` | Iterate `acceptance_surfaces`, find entry with `test_layout_convention` set |
| Semantic fit | Clean — sister-test discovery is its own concern | Loose — `acceptance_surfaces` was modeled for E2E harnesses; unit-test layout is a different thing |
| Override expressiveness | `overrides: [TestLayoutRule, ...]` natural | Awkward — would need a sub-list on the surface entry |
| Rendering / docs | New section in `system_context_renderer.py` | Existing section, extended row |

The plan reviewer's point is fair: **B is not crazy**. Reuse is cheap, the schema delta is small, and unit-test layout *is* arguably a kind of acceptance-test surface. The case against B is that `acceptance_surfaces` today encodes "what end-to-end harness exists for this product" — `name: "Web App"`, `signals: ["Next.js in package.json"]` — and overloading it with "the unit-test mapping rules to feed a sprint-time validator" is semantically off. The data we need (a *convention reference plus an overrides list of mapping rules*) doesn't fit naturally into the `name`/`signals`/`status`/`harness` shape; the proposed `test_layout_convention` field is a sidecar, and the override list (essential for monorepo and customer-declared layouts) has nowhere to go without further bloating the entry.

### 3d. Recommendation: Option A

Pick A. Reasons, in priority order:

1. **Honesty about what the data is.** Sister-test discovery is a sprint-time validator concern, not an acceptance-test description. A separate field names what's actually being modeled.
2. **The `overrides` list belongs somewhere.** Customer-declared mapping rules are the main reason this whole design exists (so non-pytest projects work). Option A gives them a natural home (`test_layout.overrides`); Option B forces them into a sublist on a surface entry that wasn't built for it.
3. **Schema simplicity at the call site.** `discover_sister_tests` reads `system_context["test_layout"]` directly. Under B it iterates surfaces looking for a magic name or a magic field, branching on which rule it finds first.
4. **The CLI/schema cost of A is small.** One new validator function (~20 lines, mirrors `_validate_acceptance_surface_entry`), one new CLI subcommand pair (`edit-test-layout`, `get-test-layout`), one new section in the renderer. Comparable to what was added for `acceptance_surfaces` and `branching_strategy`.

If the implementer disagrees and chooses B, the validator API in §4 doesn't change — only the lookup site does (a one-function helper that pulls the convention from wherever it lives). That keeps the disagreement cheap to reverse.

---

## 4. Validator API

The validator stays a pure function. Layout strategies are data, not classes.

### 4a. Data model

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class TestLayoutRule:
    """One source→test mapping rule.

    All fields are JSON-serializable so customer-declared overrides
    can round-trip through system_context.json.
    """
    # PurePosixPath glob filtering which sources this rule applies to.
    # Examples: "**/*.go", "src/bin/*.rs", "**/scripts/*.py",
    # "**/*.{js,jsx,ts,tsx}". Brace expansion (`{a,b,c}`) is applied
    # here too — same custom expander used for `test_glob` — then each
    # expanded branch is matched against project-relative source paths
    # via PurePosixPath.match.
    source_pattern: str

    # Named strategy for deriving the test-name stem from the source path.
    # See §4b for the full registry. Adding a new strategy requires a
    # code change (deliberate — reviewers see a new pattern of test discovery).
    stem_extractor: str

    # Path template with {stem} and {dir} placeholders. After substitution
    # the result is split on `,` inside `{...}` brace groups (custom expansion,
    # NOT pathlib glob — pathlib doesn't do brace expansion), then each
    # expanded path is fed to project_root.glob(). Examples:
    #   "tests/**/test_{stem}*.py"            → one glob
    #   "{dir}/{stem}_test.go"                → one glob, no expansion
    #   "{dir}/{stem}.test.{js,ts,jsx,tsx}"   → four globs (one per ext)
    test_glob: str

    # Optional: source-path basenames to skip even when source_pattern matches.
    # Example for python_pytest: ("__init__.py", "conftest.py").
    skip_basenames: tuple[str, ...] = ()

    # Optional: source-path basename SUFFIXES to skip. Example for go_native:
    # ("_test.go",) so the rule doesn't try to find a sister for a test file.
    skip_suffixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TestLayout:
    """The convention bundle for a project."""
    convention: str  # "python_pytest" | "go_native" | "js_jest" | "rust_cargo" | "custom"
    rules: tuple[TestLayoutRule, ...]
    # Customer-declared additions. Resolved AFTER built-ins so customers
    # can broaden coverage without re-declaring built-in rules.
    overrides: tuple[TestLayoutRule, ...] = ()
```

### 4b. Stem-extractor registry

The registry is enumerated. Adding a name requires a code change:

| Name | What it does | Used by |
|---|---|---|
| `basename_no_ext` | `Path(source).stem` — basename without final extension | python_pytest, go_native, js_jest, rust_cargo (all four built-ins) |
| `skill_dir_xp_strip` | For `skills/<name>/preload.sh`: returns `<name>` with `xp-` stripped and dashes replaced by `_`. Returns `None` when the path doesn't match the `skills/<name>/preload.sh` shape. | python_pytest (R2 in §2a *as extended for this plugin*; not in the project-generic R1/R2 rules) |

The `skill_dir_xp_strip` extractor exists for backward compatibility with the deferred sprint-079 wiring. It is NOT part of the project-generic built-in rules — this plugin's own `system_context.json` would name it via `stem_extractor: "skill_dir_xp_strip"` inside an `override` `TestLayoutRule`. Other plugin users get the two project-generic rules and nothing else.

**Note on extensibility.** Overrides per §4a are `TestLayoutRule` instances; they reference an extractor *by name*. Adding a NEW extractor name (different stem-extraction logic, e.g. `skill_dir_xp_strip` for an unrelated naming convention) requires a code change to this registry — overrides cannot smuggle in new extractor functions via JSON. The registry is intentionally closed so that `system_context.json` data stays inert and reviewable; if a plugin needs a new extractor, it ships a PR against this module along with its override declaration.

If `stem_extractor` returns `None`, the rule does not apply to this source — the validator continues to the next rule.

### 4c. The function

```python
def discover_sister_tests(
    source_path: str,
    layout: TestLayout,
    project_root: Path,
) -> list[str]:
    """Return existing sister-test files for one source path.

    Pure function. No SMM writes, no mutation. Returns sorted, deduped,
    project-relative POSIX path strings (matching the format used in
    file_domain entries elsewhere). Returns empty list when no rule
    matches or no test files exist on disk — never raises for "no match".

    Raises ValueError if source_path is absolute (callers must pass
    project-relative paths) or if a rule's stem_extractor name is not
    in the registry (§4b).
    """
```

Return type is `list[str]` (not `list[Path]`) so the result drops directly into `file_domain` entries without conversion. POSIX paths so the format is stable across OS.

### 4d. Built-in convention table

The table is fully specified — no `...` punts:

```python
BUILTIN_LAYOUTS: dict[str, TestLayout] = {
    "python_pytest": TestLayout(
        convention="python_pytest",
        rules=(
            # R1: top-level tests/ tree
            TestLayoutRule(
                source_pattern="**/*.py",
                stem_extractor="basename_no_ext",
                test_glob="tests/**/test_{stem}*.py",
                skip_basenames=("__init__.py", "conftest.py"),
            ),
            # R2: adjacent tests directory
            TestLayoutRule(
                source_pattern="**/*.py",
                stem_extractor="basename_no_ext",
                test_glob="{dir}/tests/test_{stem}*.py",
                skip_basenames=("__init__.py", "conftest.py"),
            ),
        ),
    ),
    "go_native": TestLayout(
        convention="go_native",
        rules=(
            TestLayoutRule(
                source_pattern="**/*.go",
                stem_extractor="basename_no_ext",
                test_glob="{dir}/{stem}_test.go",
                skip_suffixes=("_test.go",),
            ),
        ),
    ),
    "js_jest": TestLayout(
        convention="js_jest",
        rules=(
            # R1: sibling .test/.spec files
            TestLayoutRule(
                source_pattern="**/*.{js,jsx,ts,tsx}",
                stem_extractor="basename_no_ext",
                test_glob="{dir}/{stem}.test.{js,jsx,ts,tsx}",
                skip_suffixes=(".d.ts", ".test.js", ".test.jsx",
                               ".test.ts", ".test.tsx",
                               ".spec.js", ".spec.jsx",
                               ".spec.ts", ".spec.tsx"),
            ),
            # Also try .spec. variant
            TestLayoutRule(
                source_pattern="**/*.{js,jsx,ts,tsx}",
                stem_extractor="basename_no_ext",
                test_glob="{dir}/{stem}.spec.{js,jsx,ts,tsx}",
                skip_suffixes=(".d.ts", ".test.js", ".test.jsx",
                               ".test.ts", ".test.tsx",
                               ".spec.js", ".spec.jsx",
                               ".spec.ts", ".spec.tsx"),
            ),
            # R2: __tests__ directory
            TestLayoutRule(
                source_pattern="**/*.{js,jsx,ts,tsx}",
                stem_extractor="basename_no_ext",
                test_glob="{dir}/__tests__/{stem}.test.{js,jsx,ts,tsx}",
                skip_suffixes=(".d.ts",),
            ),
        ),
    ),
    "rust_cargo": TestLayout(
        convention="rust_cargo",
        rules=(
            # Integration tests for binaries: src/bin/<x>.rs → tests/<x>.rs
            TestLayoutRule(
                source_pattern="src/bin/*.rs",
                stem_extractor="basename_no_ext",
                test_glob="tests/{stem}.rs",
            ),
            # NOTE: src/lib.rs is intentionally NOT mapped. Rust integration
            # tests live under tests/ but their naming is per-capability,
            # not per-source-file — there is no honest 1:1 mapping. A
            # blanket tests/*.rs rule would auto-include every integration
            # test whenever a story touches src/lib.rs and silently blow
            # up file_domain. Plugins that want lib.rs mapped must declare
            # an `override` rule with their project-specific naming
            # convention (e.g. tests/lib_<capability>.rs).
        ),
    ),
}
```

### 4e. Where it gets called

`_auto_include_sister_tests` in `save_sprint.py` becomes a thin loop over each story's `file_domain`, calling `discover_sister_tests` per source entry, then assembling additions and emitting the existing status event. The convention lookup happens once per `run()` call:

```python
def _resolve_layout(smm_dir: Path) -> TestLayout | None:
    """Read system_context.json, return the project's TestLayout or None
    if test_layout is unset or convention is "unknown". The None case is
    handled by the caller in _auto_include_sister_tests via the Q1
    soft-warn policy (record one low-severity concern per session, then
    no-op). _resolve_layout itself never writes events."""
```

The validator becomes ~40 lines plus the data tables. The current `_sister_test_stem` and `_find_sister_tests` are deleted entirely.

---

## 5. Wiring plan

The current state: three subcommands write sprint state, none of them go through `save_sprint.run()`.

### 5a. What `save_sprint.run()` already does

Reading `save_sprint.py:119-154` shows `run()` is a side-effect bundle, not just a save:

1. Snapshot whether `.accept` marker is present (line 127).
2. `sprint_store.save_sprint(smm_dir, data)` — atomic write + schema validation (line 129).
3. `_transition_target_milestone(data, smm_dir)` — flip the target milestone in `execution_plan.json` from `planned` to `in-progress` if the sprint targets a milestone, recording concerns on every failure mode (line 131).
4. If `.accept` marker was present and the sprint now has no in-progress stories, treat as acceptance completion: clear the marker, append an `iteration_complete` status event, and (if the sprint is fully done) print a sprint-review nudge to stdout (lines 135-153).

Adding sister-test discovery to `run()` makes it a fifth step (between #1's snapshot and #2's save, so the in-memory `data` carries the appended `file_domain` entries when persisted). The wiring fix matters because **none of this side-effect bundle currently runs from skill flows.** Today milestone transition, marker handling, and the review nudge all live in `run()` — and they're as dead as the validator.

### 5b. The three wiring changes

Each of these is mechanically a one-line change in `sprint_cli.py`:

- **`_cmd_create` (line 165):** replace `store.save_sprint(args.smm_dir, data)` with `save_sprint.run(data, args.smm_dir)`. Sprint-creation flow (xp-sprint-start Step 6) now picks up sister tests + milestone transition.
- **`_cmd_add_story` (line 185):** replace `store.save_sprint(args.smm_dir, sprint)` with `save_sprint.run(sprint, args.smm_dir)`. Deferred-story carry (xp-work-selection) and ad-hoc story addition now picks up sister tests for newly added stories.
- **`_cmd_edit_story` (line 227):** the current `store.edit_story(args.smm_dir, args.story_id, updates)` loads, mutates, and saves internally. The simplest reshape: load the sprint, apply `updates` to the named story, hand the resulting full sprint dict to `save_sprint.run()`. (Implementation detail — could also be a new `save_sprint.run_for_edit(story_id, updates, smm_dir)` helper that internally does the load+mutate+run.)

For `_cmd_update_story` (story-status flips), `_cmd_update_story_branch`, and `_cmd_update_story_if`: these don't change `file_domain`, so routing them through `run()` adds no new sister-test behavior. They *do* benefit from the milestone-transition + accept-marker side effects — recommend wiring them through `run()` too, but that's out of scope for "make sister-test discovery work". Future cleanup story.

### 5c. Test surface — there is none locking the bypass

A search of `plugins/xp-agents/tests/` for `store\.save_sprint|store\.edit_story` mock/assert patterns finds no test that asserts the three subcommands take the bypass path. Existing tests catch saved-sprint *shape* regressions but do not gate the *call path*. The wiring change is mechanically safe.

The deferred branch (`paulingalls/story-001-sister-test-validator`) added 217 lines of test for the validator in `test_sprint_start.py`. Those tests exercised `save_sprint.run()` directly, so they don't lock the *bypass* either. They'll need to be retained — and rewritten against `discover_sister_tests` rather than the now-deleted `_sister_test_stem` — when the implementation milestone runs.

### 5d. Why sprint-079's placement wasn't enough

The deferred branch put the validator inside `save_sprint.run()` — the right architectural spot — but stopped there. Since the three subcommands bypass `run()`, the validator landed on dead code, alongside the milestone-transition and accept-marker handling that have *also* been silently no-opping. The fix is wiring (§5b), not relocation. The CHANGELOG note that flagged this story for redesign caught the project-baked-in heuristic but missed the dead-code wiring; both need to be fixed together.

---

## 6. Decisions and open questions

### Decisions made (do not re-litigate)

**D1. Ship a default convention bundle for Python/Go/JS/Rust.** Forcing every plugin user to hand-author a `TestLayout` for vanilla pytest / go test / jest / cargo would defeat the point of "the validator works for any plugin user." Built-in conventions cover the 90% case; `test_layout.overrides` covers the 10% (and absorbs Ruby/Java/.NET until built-in demand emerges).

**D2. Never auto-scaffold missing tests.** Inherited from sprint-079 story-001 and re-affirmed here. The validator only appends tests that already exist on disk. (The `xp-scaffold-acceptance` skill is a different surface — that one scaffolds, but only for acceptance harnesses, only with explicit customer approval, and only for one configured surface at a time.)

### Open questions

**Q1. What happens for projects with no declared `test_layout`?** Three credible behaviors:

- **(a) Silent no-op.** `_resolve_layout` returns `None`; `_auto_include_sister_tests` does nothing; sprint write proceeds. Most permissive, but customers wonder why their tests aren't being auto-included.
- **(b) Soft warn.** Append a low-severity `concern` event the first time per session, then no-op. Discoverable but not blocking.
- **(c) Require declaration.** Refuse to write sprint until `test_layout` is set. Loud but heavy-handed.

**Recommendation:** (b). It matches the existing pattern — `save_sprint._record_concern` already handles soft signals around sprint writes — and it's the least surprising. Implementer should confirm before coding.

**Q2. How do auto-discovery failures surface?** `xp-system-context` probes for marker files. Failure modes:

- No marker found → unknown convention. Recommendation: write `convention: "unknown"` and let Q1's behavior take over.
- Multiple markers found (Python *and* JS in the same monorepo) → ambiguous. Recommendation: write the first match and record an `assumption` event; the customer can edit via `edit-test-layout` to disambiguate.
- Marker present but malformed (e.g., `Cargo.toml` with no `[package]`) → treat as missing.

**Q3. Per-story override?** Some stories may want to opt out (e.g., editing source without touching tests because the test changes belong to a different story). Today the answer is "the planner removes the auto-included entry, then the validator re-adds it." A `"skip_sister_tests": true` flag on a story would solve it. **Defer.** Land discovery first; add the opt-out only if it proves needed.

---

## Acceptance for this design

This document is the only design source the implementation milestone needs. It specifies:

- The four conventions and their mapping rules (§2)
- The schema field name, auto-discovery heuristics, and a worked non-Python example (§3, §3d)
- The validator function signature, where it gets called from, and what was wrong with the sprint-079 wiring (§4, §5)

The implementation milestone may discover edge cases not enumerated here — that's expected. What it should not need to do is re-design the surface, re-litigate Option A vs B, or re-derive the built-in conventions.

**A note on self-assertion.** AC4 ("doc is the only design source needed") is judged by this doc about itself, which is the structural risk inherent to spike acceptance. The implementation milestone should open with a brief doc-vs-reality pass — try to write the validator from this doc alone, log every gap as a question, and if the gap count exceeds, say, three substantive items, bring them back to a customer review before continuing. That pass is the load-bearing AC4 verifier, not the spike author's self-claim.
