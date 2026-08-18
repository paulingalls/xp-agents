'use strict'

// Tests for workflows/code_review.js — the broad-review orchestrator.
//
// This suite asserts ORCHESTRATION, not review quality: which agents run, how
// many, what the script does with what they return, and what it returns to the
// close. Whether a finder finds good bugs is not testable here and is not the
// question — the question is whether the fan-out, the grouping, the cap and the
// synthesis do what the close pipeline is told they do.
//
// Scope phase only at this commit. Fan-out, verification and synthesis arrive
// with their own reds.

const test = require('node:test')
const assert = require('node:assert')
const path = require('node:path')

const { runWorkflow } = require('./_workflow_harness.js')

const SCRIPT = path.join(
  __dirname, '..', '..', 'workflows', 'code_review.js',
)

const ARGS = {
  level: 'high',
  range: 'main...HEAD',
  pluginRoot: '/somewhere/plugins/xp-agents',
}

const scopeReply = (over = {}) => ({
  diffCommand: 'git diff main...HEAD',
  files: ['a.py', 'b.py'],
  summary: 'two files changed',
  conventions: '',
  ...over,
})

test('it opens by scoping, before spending anything on finders', async () => {
  // Ordering, not count: every finder prompt embeds the scope's diff command
  // and file list, so a finder launched first would review a scope that does
  // not exist yet. (This asserted `calls.length === 1` while the script was
  // scope-only — true then, and it stopped meaning anything the moment there
  // was a second phase.)
  const { calls } = await runWorkflow(SCRIPT, {
    args: ARGS,
    agent: async (_p, opts) =>
      opts.label === 'scope' ? scopeReply() : { candidates: [] },
  })
  assert.strictEqual(calls[0].opts.label, 'scope')
  assert.ok(calls.slice(1).every((c) => c.opts.phase !== 'Scope'))
})

test('the range reaches the scope agent rather than being assumed', async () => {
  // The close passes its OWN range. A script that hardcoded one would review
  // the wrong commits and still look green in every other test here.
  const { calls } = await runWorkflow(SCRIPT, {
    args: ARGS,
    agent: async () => scopeReply(),
  })
  assert.match(calls[0].prompt, /main\.\.\.HEAD/)
})

test('it returns the shape the close pipeline consumes', async () => {
  // `consume-findings` reads `findings` with file/line/summary/failure_scenario.
  // Returning some other shape is the failure that would only surface at a real
  // close, after the review had already been paid for.
  const { result } = await runWorkflow(SCRIPT, {
    args: ARGS,
    agent: async () => scopeReply(),
  })
  assert.ok(Array.isArray(result.findings))
  assert.strictEqual(typeof result.summary, 'string')
  assert.strictEqual(typeof result.stats, 'object')
})

test('an empty diff stops before spending anything', async () => {
  const { calls, result } = await runWorkflow(SCRIPT, {
    args: ARGS,
    agent: async () => scopeReply({ files: [] }),
  })
  assert.strictEqual(calls.length, 1, 'nothing may run after an empty scope')
  assert.deepStrictEqual(result.findings, [])
  assert.match(result.summary, /no changes/i)
})

// ─── Fan-out ───────────────────────────────────────────────────────────────
// Blindness is the mechanism the whole design rests on: one lens per finder,
// none of them seeing another's. A generalist pass over the same diff is what
// the per-increment review already is, and what this exists to beat.

const finderCalls = (calls) => calls.filter((c) => c.opts.phase === 'Find')

const runFinders = (over = {}) =>
  runWorkflow(SCRIPT, {
    args: { ...ARGS, ...over },
    agent: async (_p, opts) =>
      opts.label === 'scope' ? scopeReply() : { candidates: [] },
  })

test('high fans out one finder per angle it uses, plus cleanup', async () => {
  const { calls } = await runFinders({ level: 'high' })
  assert.strictEqual(finderCalls(calls).length, 5)
})

test('xhigh spends more angles, which is the only thing level changes', async () => {
  const { calls } = await runFinders({ level: 'xhigh' })
  assert.strictEqual(finderCalls(calls).length, 7)
})

test('every finder reads exactly one angle file, and never a sibling', async () => {
  // A finder handed two lenses is a generalist with extra steps. Asserting
  // "names its own" is not enough — it has to NOT name the others, or one
  // shared file with all the angles in it would pass.
  const { calls } = await runFinders({ level: 'xhigh' })
  const finders = finderCalls(calls)
  const named = finders.map(
    (c) => (c.prompt.match(/_code_review_angle_[a-z_]+\.md/g) || []),
  )
  for (const list of named) {
    assert.strictEqual(list.length, 1, `finder named ${list.length} angle files: ${list}`)
  }
  assert.strictEqual(new Set(named.flat()).size, finders.length, 'angles must be distinct')
})

test('the angle paths are absolute, built from the plugin root it was given', async () => {
  // The finder Reads this path. A relative one resolves against whatever cwd
  // the subagent happens to have, which is not knowable from here.
  const { calls } = await runFinders({})
  for (const c of finderCalls(calls)) {
    assert.match(c.prompt, /\/somewhere\/plugins\/xp-agents\/scripts\/_code_review_angle_/)
  }
})

test('a dead finder contributes nothing, rather than a hole in the count', async () => {
  // parallel() resolves a throwing thunk to null, so an unfiltered result set
  // carries one null per dead finder — which then flows into every later stage
  // as if it were a candidate.
  //
  // ASSERT THE COUNT, not that the run survived: a first draft here checked
  // only that `findings` was still an array, which is true with or without the
  // filter. Removing `.filter(Boolean)` left that draft green — measured, and
  // the reason this test looks the way it does.
  let alive = 0
  const { result } = await runWorkflow(SCRIPT, {
    args: ARGS,
    agent: async (_p, opts) => {
      if (opts.label === 'scope') return scopeReply()
      alive += 1
      if (alive === 1) throw new Error('finder died')
      return alive === 2
        ? { candidates: [{ file: 'a.py', line: 1, summary: 's', failure_scenario: 'f' }] }
        : { candidates: [] }
    },
  })
  assert.strictEqual(result.stats.candidates, 1)
})

// ─── Verify ────────────────────────────────────────────────────────────────
// Angle diversity creates false positives; independent refutation is what kills
// them. One refuter per distinct location rather than per candidate, because
// finders collide there constantly and a second agent re-reading the same lines
// buys nothing.

const verifyCalls = (calls) => calls.filter((c) => c.opts.phase === 'Verify')

const cand = (file, line, summary = 's') => ({
  file, line, summary, failure_scenario: 'f',
})

// Drives one finder's worth of candidates through the whole run.
const runVerify = async (candidates, verdictFor) => {
  let served = false
  return runWorkflow(SCRIPT, {
    args: ARGS,
    agent: async (prompt, opts) => {
      if (opts.label === 'scope') return scopeReply()
      if (opts.phase === 'Find') {
        if (served) return { candidates: [] }
        served = true
        return { candidates }
      }
      return verdictFor(prompt, opts)
    },
  })
}

const confirmAll = (prompt) => ({
  verdicts: (prompt.match(/^\[\d+\]/gm) || []).map((m, i) => ({
    index: i, verdict: 'CONFIRMED', evidence: 'quoted',
  })),
})

test('candidates at one location share a single refuter', async () => {
  const { calls } = await runVerify(
    [cand('a.py', 7, 'one'), cand('a.py', 7, 'two'), cand('a.py', 7, 'three'), cand('a.py', 7, 'four')],
    confirmAll,
  )
  assert.strictEqual(verifyCalls(calls).length, 1)
})

test('distinct locations get their own refuter', async () => {
  const { calls } = await runVerify(
    [cand('a.py', 7), cand('a.py', 9), cand('b.py', 7)],
    confirmAll,
  )
  assert.strictEqual(verifyCalls(calls).length, 3)
})

test('a refuter sees every candidate at its location, indexed', async () => {
  // Grouping is not deduping: two findings at one line may be one issue or two,
  // and only the refuter can tell. Collapsing them here would silently discard
  // whichever the first finder did not describe.
  const { calls } = await runVerify(
    [cand('a.py', 7, 'first claim'), cand('a.py', 7, 'second claim')],
    confirmAll,
  )
  const prompt = verifyCalls(calls)[0].prompt
  assert.match(prompt, /\[0\]/)
  assert.match(prompt, /\[1\]/)
  assert.match(prompt, /first claim/)
  assert.match(prompt, /second claim/)
})

test('REFUTED candidates do not reach the report', async () => {
  const { result } = await runVerify([cand('a.py', 7, 'wrong')], () => ({
    verdicts: [{ index: 0, verdict: 'REFUTED', evidence: 'the line says otherwise' }],
  }))
  assert.strictEqual(result.findings.length, 0)
  assert.strictEqual(result.stats.refuted, 1)
})

test('CONFIRMED and PLAUSIBLE both survive', async () => {
  // PLAUSIBLE is not a soft REFUTED. A race or a rare-path nil is real and
  // uncertain, and dropping it here would make the recall-biased ladder the
  // refuter is given a lie.
  const { result } = await runVerify([cand('a.py', 7, 'x'), cand('b.py', 3, 'y')], (p) => ({
    verdicts: (p.match(/^\[\d+\]/gm) || []).map((_m, i) => ({
      index: i,
      verdict: p.includes('x') ? 'CONFIRMED' : 'PLAUSIBLE',
      evidence: 'e',
    })),
  }))
  assert.strictEqual(result.findings.length, 2)
})

test('a candidate the refuter never ruled on is dropped, not admitted', async () => {
  // The refuter returned a verdict for one of two. Admitting the unjudged one
  // would put a finding in the report that nothing verified — which is the
  // failure the verify phase exists to prevent, arriving through the back door.
  const { result } = await runVerify([cand('a.py', 7, 'judged'), cand('a.py', 7, 'ignored')], () => ({
    verdicts: [{ index: 0, verdict: 'CONFIRMED', evidence: 'e' }],
  }))
  assert.strictEqual(result.findings.length, 1)
  assert.match(result.findings[0].summary, /judged/)
})

test('a refuter that dies drops its group rather than passing it through', async () => {
  const { result } = await runVerify([cand('a.py', 7)], () => null)
  assert.strictEqual(result.findings.length, 0)
})

test('the refuter is given the verdict ladder as shipped prose', async () => {
  const { calls } = await runVerify([cand('a.py', 7)], confirmAll)
  assert.match(verifyCalls(calls)[0].prompt, /_code_review_verdict_ladder\.md/)
})

test('a scope agent that dies is reported, not treated as an empty diff', async () => {
  // agent() returns null when a subagent dies on a terminal error. Reading that
  // as "no changes" would report a clean review of a diff nobody looked at —
  // the worst available outcome, because the close then merges on it.
  const { result } = await runWorkflow(SCRIPT, {
    args: ARGS,
    agent: async () => null,
  })
  assert.ok(result.error, 'a dead scope agent must surface as an error')
  assert.doesNotMatch(result.error, /no changes/i)
})
