export const meta = {
  name: 'xp-code-review',
  description:
    'Broad correctness review: blind angle finders over the close diff, an independent refuter per location, then a ranked and capped report.',
  whenToUse:
    'Close Step 4b, when the cumulative diff crosses the review threshold. Pass args as an object: {level, range, pluginRoot}.',
  phases: [
    { title: 'Scope', detail: 'Pin the diff command, the changed files and the conventions' },
    { title: 'Find', detail: 'One blind finder per angle, each with only its own lens' },
    { title: 'Verify', detail: 'An independent refuter per candidate location' },
    { title: 'Synthesize', detail: 'Merge by root cause, rank, and report' },
  ],
}

// The one broad multi-agent correctness pass in this process. Launched by PATH
// from close Step 4b, which is what a built-in NAME could not be: the previous
// one was registered nowhere and the step silently did not run, for releases.
//
// CONTROL FLOW ONLY. Every lens — each finder's angle, the verdict ladder —
// lives in shipped `.md` under `scripts/`, where the language-agnostic sweep
// and the prose pins scan it. A Workflow script cannot read files, so finders
// read their own angle: they have Read, and the path arrives in args.
//
// NO IMPORTS EXIST HERE. There is no module system, so this file cannot be
// split — the 500-line cap is structural, and the only lever is prose.

// ─── Input ───
// An OBJECT, not a positional string. The built-in parsed a level out of the
// first word, so a stray token fell back to a default tier and was absorbed
// into the diff range -- a corrupted review target reported as a successful
// review. There is no such failure to warn about here.
const argsAreAnObject = typeof args === 'object' && args !== null
const input = argsAreAnObject ? args : {}
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
// ONE allowance, the same as every correctness angle. Cleanup used to get
// `perAngle * 2` while `rank()` sorts it LAST, so the caps drop it first: the
// lens least likely to survive was authorized to produce the most, spending
// finder budget and then verifier locations on candidates the report cap would
// discard ahead of a correctness finding. Found by this workflow reviewing
// itself.
const CLEANUP_ANGLE = 'cleanup'

const LEVELS = {
  high: { angles: 4, perAngle: 6, report: 10 },
  xhigh: { angles: 6, perAngle: 8, report: 15 },
  max: { angles: 6, perAngle: 8, report: 15 },
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
const REPORT_CAP = params.report

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
    agent(finderPrompt(angle, params.perAngle), {
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

// ─── Synthesize ───
// Blind finders describe one defect several ways, so the report needs merging.
// This is also the LAST place a verified finding can be lost, which is why every
// branch below is about not losing one: the cap is the only thing permitted to
// drop a finding, and it announces itself when it does.
const rank = (c) => (c.angle === CLEANUP_ANGLE ? 2 : 0) + (c.verdict === 'PLAUSIBLE' ? 1 : 0)
const ranked = surviving.slice().sort((a, b) => rank(a) - rank(b))

const REPORT_SCHEMA = {
  type: 'object',
  required: ['summary', 'decisions'],
  properties: {
    summary: { type: 'string' },
    decisions: {
      type: 'array',
      items: {
        type: 'object',
        required: ['index'],
        properties: {
          index: { type: 'number', description: 'the [i] label of a finding to keep' },
          merge: {
            type: 'array',
            items: { type: 'number' },
            description: '[i] labels describing the same root cause, folded into this one',
          },
        },
      },
    },
  },
}

let report = null
if (ranked.length > 0) {
  phase('Synthesize')
  report = await agent(
    `## Synthesis: final code-review report\n\n${ranked.length} findings survived ` +
      `independent verification. They are numbered below.\n\n` +
      ranked
        .map(
          (c, i) =>
            `### [${i}] ${loc(c)} (${c.verdict}${c.angle === CLEANUP_ANGLE ? ', cleanup' : ''})\n` +
            `${c.summary}\nFailure scenario: ${c.failure_scenario}\nVerifier evidence: ${c.evidence}\n`,
        )
        .join('\n') +
      `\n## Instructions\nReturn decisions BY INDEX — never re-emit finding text.\n` +
      `1. One decision per distinct defect. When several findings describe the same ` +
      `root cause, keep one and list the others in its merge array.\n` +
      `2. Order most severe first. Correctness outranks cleanup.\n` +
      `3. Keep at most ${REPORT_CAP}.\n4. Write a two-to-three sentence summary.\n\n` +
      'Structured output only.',
    { label: 'synthesize', phase: 'Synthesize', schema: REPORT_SCHEMA },
  )
}

const decisions = report && Array.isArray(report.decisions) ? report.decisions : []
const claimed = new Set()
const claim = (i) => {
  if (!Number.isInteger(i) || i < 0 || i >= ranked.length || claimed.has(i)) return false
  claimed.add(i)
  return true
}

const toFinding = (c, extra = '') => ({
  file: c.file,
  line: c.line,
  summary: c.summary + extra,
  failure_scenario: c.failure_scenario,
  category: c.angle === CLEANUP_ANGLE ? 'cleanup' : 'correctness',
  verdict: c.verdict,
})

const findings = []
for (const d of decisions) {
  if (findings.length >= REPORT_CAP) break
  if (!claim(d.index)) continue
  const primary = ranked[d.index]
  const merged = (Array.isArray(d.merge) ? d.merge : []).filter(claim).map((i) => ranked[i])
  // A merged CONFIRMED lifts the entry it was folded into: otherwise the report
  // shows the softer verdict for a defect one refuter did confirm.
  const verdict = merged.some((m) => m.verdict === 'CONFIRMED') ? 'CONFIRMED' : primary.verdict
  const also = merged.length > 0 ? ` [same root cause also at: ${merged.map(loc).join(', ')}]` : ''
  findings.push({ ...toFinding(primary, also), verdict })
}

// BACKFILL. A synthesizer that returned one decision for ten findings — or died
// outright — must not silently discard the nine. They were found AND
// independently confirmed; losing them here would undo the whole pass at its
// last step, and quietly.
let backfilled = 0
for (let i = 0; i < ranked.length && findings.length < REPORT_CAP; i += 1) {
  if (claimed.has(i)) continue
  claimed.add(i)
  findings.push(toFinding(ranked[i]))
  backfilled += 1
}

// THE OTHER CAP, silent until this workflow reviewed itself: a close read 10 of
// 26 findings and was told 26 survived. Counted from `claimed`, not from
// `surviving.length - findings.length`, because a merged finding IS surfaced in
// its primary's "same root cause also at" list and is not dropped.
const findingsDropped = ranked.length - claimed.size
if (findingsDropped > 0) {
  log(
    `cap: ${ranked.length} verified findings, reporting ${findings.length}; ` +
      `${findingsDropped} dropped unreported`,
  )
}

const stats = {
  ...baseStats(),
  finders: finderAngles.length,
  candidates: candidates.length,
  verifierAgents: groups.length,
  locationsDropped,
  verified: verified.length,
  refuted,
  reported: findings.length,
  findingsDropped,
  backfilled,
}

// Sentences in a list, joined once; concatenation spliced clauses between a
// sentence and its full stop. And synthesis is SKIPPED when nothing survived
// (guarded on `ranked.length > 0`), so that case must be excluded rather than
// reported as a failure — a clean review used to announce a broken synthesis.
const synthesisFailed = ranked.length > 0 && decisions.length === 0
const sentences = [
  `${surviving.length} findings survived independent verification ` +
    `(${LEVEL}, ${finderAngles.length} angles).`,
]
if (argsAreAnObject && !PLUGIN_ROOT) {
  // Each finder READS its angle from a path built off this. Missing, every one
  // of them is handed a path that resolves nowhere and reviews with no lens —
  // and still returns candidates, so the run looks normal and is a generalist
  // pass wearing five angles' clothing.
  sentences.push(
    'WARNING: pluginRoot was empty, so no finder could read its angle — ' +
      'these findings came from unguided readers, not from the lenses.',
  )
}
if (!argsAreAnObject) {
  // The close renders this object by hand out of catted prose, so a
  // string-shaped `args` is a live mis-render, not a hypothetical. Defaulting
  // silently would review `@{upstream}...HEAD` instead of the close's own range
  // — different commits, possibly none — and report it as a successful review.
  sentences.push(
    'WARNING: args did not arrive as an object, so the level, range and ' +
      'pluginRoot were all defaulted — this may not be the range you asked for.',
  )
}
if (synthesisFailed) {
  sentences.push('Synthesis returned nothing usable, so these are ranked and unmerged.')
}
if (findingsDropped > 0) {
  sentences.push(
    `${findingsDropped} of them are NOT in this report — it hit its ` +
      `${REPORT_CAP}-finding cap.`,
  )
}
if (locationsDropped > 0) {
  sentences.push(
    `${locationsDropped} further locations were NOT verified — the review hit ` +
      `its fan-out cap.`,
  )
}

return {
  level: LEVEL,
  summary: sentences.join(' '),
  findings,
  stats,
}
