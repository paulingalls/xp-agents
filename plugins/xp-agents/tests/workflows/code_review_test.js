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
