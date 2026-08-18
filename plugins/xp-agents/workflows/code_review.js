export const meta = {
  name: 'xp-code-review',
  description:
    'Broad correctness review: blind angle finders over the close diff, an independent refuter per location, then a ranked and capped report.',
  whenToUse:
    'Close Step 4b, when the cumulative diff crosses the review threshold. Pass args as an object: {level, range, pluginRoot}.',
  phases: [{ title: 'Scope', detail: 'Pin the diff command, the changed files and the conventions' }],
}

// The one broad multi-agent correctness pass in this process, owned here rather
// than rented from a built-in name.
//
// WHY OURS. The close used to launch a built-in by NAME. That name was
// registered nowhere in the shipped build, so Step 4b silently did not run --
// for releases, while every check said the instruction was present. A script
// invoked by PATH cannot fail that way, and owning it is also what lets the
// angles below be ours: two of them exist because of defects this project
// actually shipped.
//
// WHAT IS NOT HERE, deliberately: the reviewing prose. Each finder's lens, the
// cleanup lenses and the verdict ladder live in shipped `.md` under `scripts/`,
// where the language-agnostic sweep and the prose pins already scan them. This
// file carries control flow only. A Workflow script cannot read files, so the
// finders read their own angle -- they have Read, and the path arrives in args.

// ─── Input ───
// An OBJECT, not a positional string. The built-in parsed a level out of the
// first word, so a stray token fell back to a default tier and was absorbed
// into the diff range -- a corrupted review target reported as a successful
// review. There is no such failure to warn about here.
const input = typeof args === 'object' && args !== null ? args : {}
const LEVEL = input.level || 'high'
const RANGE = input.range || ''
const PLUGIN_ROOT = input.pluginRoot || ''

// ─── Angles ───
// ORDER IS THE LEVEL. `high` takes the first four; `xhigh`/`max` take all six.
// The two with recorded evidence behind them come first on purpose: this
// project shipped two regressions that only a state/lifecycle reading would
// have caught, and produced three assert-nothing tests in a single session.
// A cheaper run should not be the one that drops them.
//
// Each name is a shipped file under `scripts/`. The prose lives there, not
// here, because that directory is scanned by the language-agnostic sweep and
// the prose pins — a lens written in one ecosystem's vocabulary is inert for
// every project using another, and this file is not somewhere that gets caught.
const CORRECTNESS_ANGLES = [
  'state_lifecycle',
  'test_vacuity',
  'line_scan',
  'removed_behavior',
  'cross_file',
  'language_pitfalls',
]
const CLEANUP_ANGLE = 'cleanup'

const LEVELS = {
  high: { angles: 4, perAngle: 6 },
  xhigh: { angles: 6, perAngle: 8 },
  max: { angles: 6, perAngle: 8 },
}

const anglePath = (name) => `${PLUGIN_ROOT}/scripts/_code_review_angle_${name}.md`
const LADDER_PATH = `${PLUGIN_ROOT}/scripts/_code_review_verdict_ladder.md`

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['verdicts'],
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        required: ['index', 'verdict', 'evidence'],
        properties: {
          index: { type: 'number', description: 'the [i] label of the candidate this verdict is for' },
          verdict: { enum: ['CONFIRMED', 'PLAUSIBLE', 'REFUTED'] },
          evidence: { type: 'string' },
        },
      },
    },
  },
}

const CANDIDATES_SCHEMA = {
  type: 'object',
  required: ['candidates'],
  properties: {
    candidates: {
      type: 'array',
      items: {
        type: 'object',
        required: ['file', 'summary', 'failure_scenario'],
        properties: {
          file: { type: 'string', description: 'repo-relative path, exactly as listed in the review scope' },
          line: { type: 'number' },
          summary: { type: 'string' },
          failure_scenario: { type: 'string' },
        },
      },
    },
  },
}

const SCOPE_SCHEMA = {
  type: 'object',
  required: ['diffCommand', 'files', 'summary'],
  properties: {
    diffCommand: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
    conventions: { type: 'string' },
  },
}

const baseStats = () => ({ level: LEVEL, finders: 0, candidates: 0, verifierAgents: 0 })

// ─── Scope ───
phase('Scope')
const scope = await agent(
  'Establish the scope of a code review.\n\n' +
    (RANGE
      ? `Review the range \`${RANGE}\`. Build the git diff command for it and run it to confirm it is non-empty.\n`
      : 'No range given — review the current branch: prefer `git diff @{upstream}...HEAD`, falling back to `git diff main...HEAD`.\n') +
    '\n1. Determine the exact diff command and run it.\n' +
    '2. List the changed files, repo-relative.\n' +
    '3. Summarize what changed in one paragraph.\n' +
    '4. Note any conventions a reviewer of this repo should know.\n\n' +
    'Return diffCommand exactly as a reviewer should run it. Structured output only.',
  { label: 'scope', phase: 'Scope', schema: SCOPE_SCHEMA },
)

// A dead scope agent is NOT an empty diff. `agent()` returns null when a
// subagent dies on a terminal error, and reading that as "nothing changed"
// would report a clean review of a diff nobody opened — on which the close then
// merges. The two outcomes are told apart here because nothing downstream can.
if (!scope) {
  return {
    level: LEVEL,
    error: 'The scope agent returned nothing, so the review never established what to read.',
    findings: [],
    stats: baseStats(),
  }
}

if (!scope.files || scope.files.length === 0) {
  return {
    level: LEVEL,
    summary: 'No changes found to review.',
    findings: [],
    stats: baseStats(),
  }
}

log(`${LEVEL} review: ${scope.files.length} changed files`)

const params = LEVELS[LEVEL] || LEVELS.high

const SCOPE_BLOCK =
  `## Review scope\nDiff command: ${scope.diffCommand}\n` +
  `Changed files (${scope.files.length}):\n` +
  scope.files.map((f) => `  - ${f}`).join('\n') +
  `\n\n## What changed\n${scope.summary}\n` +
  `\n## Conventions\n${scope.conventions || '(none noted)'}\n`

// ONE angle per finder, and the prompt names one file. A finder handed the
// whole set is a generalist with extra steps, which is what the per-increment
// review already is — the diversity is the entire reason this pass finds what
// that one does not.
const finderPrompt = (angle, cap) =>
  `## Code-review finder\n\n${SCOPE_BLOCK}\n` +
  `Read \`${anglePath(angle)}\` — that file is your assigned angle, and the ` +
  `only one you have. Run the diff command above and review THROUGH THAT LENS ` +
  `ONLY; other reviewers hold the other angles and will cover what you skip.\n\n` +
  `Surface up to ${cap} candidates, each with file, line, a one-line summary, ` +
  `and a concrete failure_scenario — the consequence someone would observe, ` +
  `not an intermediate state. Pass through every candidate you can name a ` +
  `failure for: an independent verifier judges them next, so do not silently ` +
  `drop the half-believed ones. If nothing qualifies, return an empty list.\n\n` +
  'Structured output only.'

phase('Find')
const finderAngles = [
  ...CORRECTNESS_ANGLES.slice(0, params.angles),
  CLEANUP_ANGLE,
]

const found = await parallel(
  finderAngles.map((angle) => () =>
    agent(finderPrompt(angle, angle === CLEANUP_ANGLE ? params.perAngle * 2 : params.perAngle), {
      label: `find:${angle}`,
      phase: 'Find',
      schema: CANDIDATES_SCHEMA,
    }).then((r) => {
      if (!r) return []
      log(`${angle}: ${r.candidates.length} candidates`)
      return r.candidates.map((c) => ({ ...c, angle }))
    }),
  ),
)

// `.filter(Boolean)` is not defensive: parallel() resolves a thunk that threw
// to null, so one dead finder would otherwise crash every stage after it — and
// the close has already paid for the finders that did work.
const candidates = found.filter(Boolean).flat()

// ─── Verify ───
// One refuter per distinct LOCATION, not per candidate. Blind finders collide
// constantly — several lenses land on the same line — and a second agent
// re-reading those same lines learns nothing the first did not. Grouping is NOT
// deduping: every candidate keeps its own verdict, because two findings at one
// line may be one issue or two and only the refuter can tell.
//
// The trade, stated: one dead refuter now drops every candidate at its location
// instead of one. That is the safe direction — an unjudged candidate reaching
// the report is a finding nothing verified, which is exactly what this phase
// exists to prevent.
const loc = (c) => `${c.file}${c.line != null ? `:${c.line}` : ''}`

const verifierPrompt = (group) =>
  `## Code-review verifier\n\n${SCOPE_BLOCK}\n` +
  `Read \`${LADDER_PATH}\` — it defines the three verdicts and, importantly, ` +
  `when NOT to refute.\n\n` +
  `## Candidate findings at ${loc(group[0])}\n` +
  group
    .map((c, i) => `[${i}] ${c.summary}\n    Failure scenario: ${c.failure_scenario}`)
    .join('\n') +
  `\n\nRun the diff command above, read the relevant lines, and return one ` +
  `verdict per candidate, referenced by its [i] index. Judge each on its own ` +
  `claim. Structured output only; evidence must quote or cite the lines.\n`

phase('Verify')
const byLoc = new Map()
for (const c of candidates) {
  const key = loc(c)
  if (!byLoc.has(key)) byLoc.set(key, [])
  byLoc.get(key).push(c)
}
const allGroups = [...byLoc.values()]

// THE CAP, in code rather than in a sentence. What this replaces was prose in
// the close pipeline telling the caller not to raise the tier; that file's own
// test records a customer run reaching roughly a hundred agents and says the
// risk was "narrowed, not closed". A number here closes it.
//
// Bounded on LOCATIONS, which is what refuter agents are counted by. Correctness
// angles sort first in the candidate list, so when the cap bites it keeps the
// lenses with recorded evidence behind them and drops cleanup first.
const VERIFY_CAP = 20
const groups = allGroups.slice(0, VERIFY_CAP)
const locationsDropped = allGroups.length - groups.length
if (locationsDropped > 0) {
  // Announced, never silent: a truncated review that does not say so reads as
  // a review that covered everything, which is a worse failure than the cost
  // the cap exists to avoid.
  log(
    `cap: ${allGroups.length} locations found, verifying ${groups.length}; ` +
      `${locationsDropped} dropped unverified`,
  )
}

const verifiedGroups = await parallel(
  groups.map((group) => async () => {
    const r = await agent(verifierPrompt(group), {
      label: `verify:${loc(group[0])}`,
      phase: 'Verify',
      schema: VERDICT_SCHEMA,
    })
    if (!r || !Array.isArray(r.verdicts)) return []
    const byIndex = new Map()
    for (const v of r.verdicts) {
      if (Number.isInteger(v.index) && v.index >= 0 && v.index < group.length) {
        byIndex.set(v.index, v)
      }
    }
    // A candidate with no verdict is DROPPED. It was not judged, and admitting
    // it would put an unverified finding in the report under a phase whose
    // whole purpose is that there are none.
    return group.flatMap((c, i) =>
      byIndex.has(i) ? [{ ...c, verdict: byIndex.get(i).verdict, evidence: byIndex.get(i).evidence }] : [],
    )
  }),
)

const verified = verifiedGroups.filter(Boolean).flat()
const surviving = verified.filter((c) => c.verdict !== 'REFUTED')
const refuted = verified.length - surviving.length
log(`verify: ${verified.length} judged, ${surviving.length} kept, ${refuted} refuted`)

const stats = {
  ...baseStats(),
  finders: finderAngles.length,
  candidates: candidates.length,
  verifierAgents: groups.length,
  locationsDropped,
  verified: verified.length,
  refuted,
}

return {
  level: LEVEL,
  summary:
    `${surviving.length} findings survived independent verification ` +
    `(${LEVEL}, ${finderAngles.length} angles)` +
    (locationsDropped > 0
      ? `; ${locationsDropped} further locations were NOT verified — the review hit its cap.`
      : '.'),
  findings: surviving.map((c) => ({
    file: c.file,
    line: c.line,
    summary: c.summary,
    failure_scenario: c.failure_scenario,
    category: c.angle === CLEANUP_ANGLE ? 'cleanup' : 'correctness',
    verdict: c.verdict,
  })),
  stats,
}
