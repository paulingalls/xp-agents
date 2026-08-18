'use strict'

// Tests for workflows/code_review.js — synthesis, the report cap, and the
// warnings for args that arrive malformed.
//
// Split from `code_review_test.js` when it crossed the 500-line cap; that
// file's ceiling entry named this as the cohesive group, and it is — everything
// here is about what happens AFTER verification returns.

const test = require('node:test')
const assert = require('node:assert')

const { runWorkflow } = require('./_workflow_harness.js')
const {
  SCRIPT, ARGS, scopeReply, cand, runVerify, confirmAll,
} = require('./_code_review_fixtures.js')

const synth = (decisions, summary = 'reviewed') => (prompt, opts) =>
  opts.phase === 'Synthesize' ? { summary, decisions } : confirmAll(prompt)

test('it merges findings the synthesizer says share a root cause', async () => {
  const { result } = await runVerify(
    [cand('a.py', 7, 'same bug seen one way'), cand('b.py', 9, 'same bug seen another')],
    synth([{ index: 0, merge: [1] }]),
  )
  assert.strictEqual(result.findings.length, 1)
  assert.match(result.findings[0].summary, /b\.py:9|same root cause/)
})

test('a merged CONFIRMED lifts the entry it was folded into', async () => {
  // Otherwise the report shows PLAUSIBLE for a defect one refuter confirmed,
  // and the close reads it as the softer finding.
  let n = 0
  const { result } = await runVerify(
    [cand('a.py', 7, 'first'), cand('b.py', 9, 'second')],
    (prompt, opts) => {
      // index 1, NOT 0: ranking sorts CONFIRMED ahead of PLAUSIBLE, so a
      // decision naming index 0 has a CONFIRMED primary already and the lift
      // never runs. A first draft did exactly that and stayed green when the
      // lift was removed — measured, not guessed.
      if (opts.phase === 'Synthesize') return { summary: 's', decisions: [{ index: 1, merge: [0] }] }
      n += 1
      return { verdicts: [{ index: 0, verdict: n === 1 ? 'PLAUSIBLE' : 'CONFIRMED', evidence: 'e' }] }
    },
  )
  assert.strictEqual(result.findings.length, 1)
  assert.strictEqual(result.findings[0].verdict, 'CONFIRMED')
})

test('a verified finding the synthesizer ignored is still reported', async () => {
  // THE LOSS THIS GUARDS. A synthesizer that returns one decision for three
  // findings must not silently discard the other two — they were found and
  // independently confirmed, and the cap is the only thing allowed to drop a
  // finding.
  const { result } = await runVerify(
    [cand('a.py', 1, 'one'), cand('b.py', 2, 'two'), cand('c.py', 3, 'three')],
    synth([{ index: 0 }]),
  )
  assert.strictEqual(result.findings.length, 3)
})

test('a synthesizer that dies costs the merge, never the findings', async () => {
  const { result } = await runVerify(
    [cand('a.py', 1, 'one'), cand('b.py', 2, 'two')],
    (prompt, opts) => (opts.phase === 'Synthesize' ? null : confirmAll(prompt)),
  )
  assert.strictEqual(result.findings.length, 2)
  assert.match(result.summary, /unmerged|synthes/i)
})

test('a finder that could not read its angle is reported, not averaged in', async () => {
  // An empty pluginRoot the script can see. A non-empty WRONG one it cannot —
  // it has no filesystem — and that is the likelier mis-render, because the
  // close substitutes the path into the launch literal by hand. The finder is
  // the only party that knows, so it has to say, and the report has to carry
  // it: otherwise a lens-less pass is indistinguishable from a working one.
  const { result } = await runWorkflow(SCRIPT, {
    args: { level: 'high', range: 'main...HEAD', pluginRoot: '/wrong/place' },
    agent: async (_p, opts) =>
      opts.label === 'scope'
        ? scopeReply()
        : { candidates: [], angleRead: false },
  })
  assert.match(result.summary, /could not read their angle/)
})

test('angles read normally produce no warning', async () => {
  // Non-vacuity: the warning must key on the finder's answer, not fire always.
  const { result } = await runWorkflow(SCRIPT, {
    args: ARGS,
    agent: async (_p, opts) =>
      opts.label === 'scope' ? scopeReply() : { candidates: [], angleRead: true },
  })
  assert.doesNotMatch(result.summary, /could not read their angle/)
})

test('an unrecognised level says so instead of quietly reviewing at another', async () => {
  // `LEVELS[LEVEL] || LEVELS.high` fell to the default silently while the
  // report kept announcing the level that was ASKED for, so a typo produced a
  // cheaper review reported as the expensive one.
  const { result } = await runWorkflow(SCRIPT, {
    args: { level: 'higher', range: 'main...HEAD', pluginRoot: '/p' },
    agent: async (_p, opts) =>
      opts.label === 'scope' ? scopeReply() : { candidates: [] },
  })
  assert.match(result.summary, /level .higher. is not one of/i)
})

test('an inherited Object key is not a level', async () => {
  // The sharp edge, and the reason the fix is `Object.hasOwn` rather than a
  // nicer default. `LEVELS['constructor']` resolves up the prototype chain to
  // `Object` — truthy, so `||` never fires — and every field then reads
  // undefined: REPORT_CAP undefined makes `findings.length >= REPORT_CAP`
  // false forever, so THE REPORT CAP STOPS EXISTING, and
  // `CORRECTNESS_ANGLES.slice(0, undefined)` returns nothing, so the run has no
  // correctness angles at all. A lens-less, unbounded review reported as `high`.
  const { calls, result } = await runWorkflow(SCRIPT, {
    args: { level: 'constructor', range: 'main...HEAD', pluginRoot: '/p' },
    agent: async (_p, opts) =>
      opts.label === 'scope' ? scopeReply() : { candidates: [] },
  })
  const finders = calls.filter((c) => c.opts.phase === 'Find')
  assert.ok(finders.length > 1, `expected the correctness angles to run: ${finders.length}`)
  assert.match(result.summary, /not one of/i)
})

test('an empty pluginRoot says the finders had no lens', async () => {
  // Each finder READS its angle off this path. Missing, all of them get a path
  // that resolves nowhere, review unguided, and still return candidates — so
  // the run looks completely normal and is a generalist pass wearing five
  // angles' clothing. That is the failure this whole design exists to beat, so
  // it cannot be the one that arrives silently.
  const { result } = await runWorkflow(SCRIPT, {
    args: { level: 'high', range: 'main...HEAD' },
    agent: async (_p, opts) =>
      opts.label === 'scope' ? scopeReply() : { candidates: [] },
  })
  assert.match(result.summary, /pluginRoot was empty/)
})

test('a non-object args says so instead of quietly reviewing something else', async () => {
  // The close renders this object BY HAND out of prose that is `cat` raw, so a
  // string-shaped args is a live mis-render. Defaulting silently would review
  // `@{upstream}...HEAD` — different commits, possibly none — and return it as
  // a successful close review.
  const { result } = await runWorkflow(SCRIPT, {
    args: 'high main...HEAD',
    agent: async (_p, opts) =>
      opts.label === 'scope' ? scopeReply() : { candidates: [] },
  })
  assert.match(result.summary, /args did not arrive as an object/)
})

test('every angle gets the same candidate allowance', async () => {
  // Cleanup used to get twice it, while rank() sorts cleanup LAST so the caps
  // drop it first — the lens least likely to survive was allowed to produce the
  // most. Asserted on the prompts, which is where the number reaches an agent.
  const { calls } = await runWorkflow(SCRIPT, {
    args: ARGS,
    agent: async (_p, opts) =>
      opts.label === 'scope' ? scopeReply() : { candidates: [] },
  })
  const caps = calls
    .filter((c) => c.opts.phase === 'Find')
    .map((c) => (c.prompt.match(/at most (\d+)/) || [])[1])
  assert.ok(caps.length > 1, 'expected several finders')
  assert.strictEqual(new Set(caps).size, 1, `finder caps differ: ${caps.join(', ')}`)
})

test('the report cap says how many verified findings it left out', async () => {
  // THE BUG THIS WORKFLOW FOUND IN ITSELF, on its first real run. 26 findings
  // survived verification, REPORT_CAP kept 10, and the summary said "26
  // findings survived independent verification" with no mention that 16 of
  // them were not in the array the close is told to read. The close would have
  // merged believing every finding was addressed.
  //
  // Only the LOCATION cap announced itself. The report cap — the one that
  // discards findings already paid for by a finder and a refuter — was silent,
  // in a file whose own comment claims "the cap is the only thing permitted to
  // drop a finding, and it announces itself when it does".
  const many = Array.from({ length: 14 }, (_v, i) => cand(`f${i}.py`, i, `bug ${i}`))
  const { result } = await runVerify(many, confirmAll)

  assert.strictEqual(result.findings.length, 10, 'REPORT_CAP still bounds the array')
  assert.strictEqual(result.stats.verified, 14)
  assert.strictEqual(result.stats.findingsDropped, 4)
  assert.match(
    result.summary,
    /4 .*NOT in this report/,
    `a truncated report must say so in the summary the close reads: ${result.summary}`,
  )
})

test('a review that found nothing does not report a broken synthesis', async () => {
  // `report && decisions.length > 0` cannot tell "nothing to merge" from
  // "the merge died", so a CLEAN review announced a synthesis failure — and
  // with a doubled period, because the clause was spliced between a sentence
  // and its full stop. An operator reading that re-runs a pass that worked.
  const { result } = await runVerify([], () => ({ candidates: [] }))

  assert.strictEqual(result.findings.length, 0)
  assert.doesNotMatch(result.summary, /nothing usable/i)
  assert.doesNotMatch(result.summary, /\.\./, `doubled punctuation: ${result.summary}`)
})

test('a synthesis that really died still says so', async () => {
  // The counterpart, so the fix above cannot be "never mention synthesis".
  const { result } = await runVerify(
    [cand('a.py', 1, 'one')],
    (prompt, opts) => (opts.phase === 'Synthesize' ? null : confirmAll(prompt)),
  )
  assert.match(result.summary, /nothing usable/i)
})

test('a decision naming a finding twice cannot duplicate it', async () => {
  const { result } = await runVerify(
    [cand('a.py', 1, 'one'), cand('b.py', 2, 'two')],
    synth([{ index: 0, merge: [1] }, { index: 1 }]),
  )
  assert.strictEqual(result.findings.length, 1)
})

test('an out-of-range decision index is ignored, not crashed on', async () => {
  const { result } = await runVerify([cand('a.py', 1, 'one')], synth([{ index: 99 }, { index: 0 }]))
  assert.strictEqual(result.findings.length, 1)
})
