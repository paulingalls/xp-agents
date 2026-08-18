'use strict'

// Tests for workflows/code_review.js — scope, fan-out and verification.
//
// This suite asserts ORCHESTRATION, not review quality: which agents run, how
// many, what the script does with what they return, and what it returns to the
// close. Whether a finder finds good bugs is not testable here and is not the
// question — the question is whether the fan-out, the grouping and the caps do
// what the close pipeline is told they do.
//
// Synthesis, the report caps and the malformed-args warnings live in
// `code_review_synthesis_test.js`; the split came when this file crossed the
// 500-line cap. Shared fixtures are in `_code_review_fixtures.js`.

const test = require('node:test')
const assert = require('node:assert')

const { runWorkflow } = require('./_workflow_harness.js')
const {
  SCRIPT, ARGS, scopeReply, finderCalls, verifyCalls, cand, runVerify, confirmAll,
} = require('./_code_review_fixtures.js')

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
  //
  // VACUOUS UNTIL FIXED, and caught by this workflow reviewing itself: the
  // discriminator was `p.includes('x')` against the whole verifier prompt, and
  // every prompt carries the SCOPE BLOCK — the diff command, the changed file
  // list, the summary. So it was true every time, both candidates came back
  // CONFIRMED, and a test named for two verdicts exercised one.
  //
  // A bare filename is the same trap one level down: `a.py` is in the scope
  // block of BOTH prompts. The only text unique to a group is its own
  // `## Candidate findings at <loc>` header, which is the grouping this suite
  // pins elsewhere. Assert the verdicts that came back, not just the count.
  const { result } = await runVerify([cand('a.py', 7, 'x'), cand('b.py', 3, 'y')], (p) => ({
    verdicts: (p.match(/^\[\d+\]/gm) || []).map((_m, i) => ({
      index: i,
      verdict: /Candidate findings at a\.py/.test(p) ? 'CONFIRMED' : 'PLAUSIBLE',
      evidence: 'e',
    })),
  }))
  assert.strictEqual(result.findings.length, 2)
  assert.deepStrictEqual(
    result.findings.map((f) => f.verdict).sort(),
    ['CONFIRMED', 'PLAUSIBLE'],
  )
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

// ─── Cost ──────────────────────────────────────────────────────────────────
// The bound this replaces was PROSE — a sentence in the close pipeline telling
// the caller not to raise the tier. Its own test file records a customer run
// that reached roughly a hundred agents and says the risk was "narrowed, not
// closed". Owning the script is what lets it be closed, and a cap that drops
// work silently is a different way of lying about coverage.

test('the refuter fan-out is capped, not merely discouraged', async () => {
  const many = Array.from({ length: 40 }, (_v, i) => cand('a.py', i))
  const { calls } = await runVerify(many, confirmAll)
  assert.ok(
    verifyCalls(calls).length <= 20,
    `expected a cap, saw ${verifyCalls(calls).length} refuters`,
  )
})

test('what the cap drops is announced, never dropped quietly', async () => {
  // Silent truncation reads as "everything was covered". A capped review that
  // says so is a bounded review; one that does not is a wrong one.
  const many = Array.from({ length: 40 }, (_v, i) => cand('a.py', i))
  const { logs } = await runVerify(many, confirmAll)
  assert.ok(
    logs.some((l) => /cap/i.test(l) && /\d/.test(l)),
    `no log names the cap and a count: ${JSON.stringify(logs)}`,
  )
})

test('the report says it was capped, so the close can see it', async () => {
  const many = Array.from({ length: 40 }, (_v, i) => cand('a.py', i))
  const { result } = await runVerify(many, confirmAll)
  assert.ok(result.stats.locationsDropped > 0)
})

test('an ordinary review is not capped at all', async () => {
  // The control. Without it the cap tests pass against a script that caps
  // everything to zero.
  const { calls, result } = await runVerify([cand('a.py', 1), cand('b.py', 2)], confirmAll)
  assert.strictEqual(verifyCalls(calls).length, 2)
  assert.strictEqual(result.stats.locationsDropped, 0)
})

// ─── Synthesize ────────────────────────────────────────────────────────────
// Blind finders describe one defect several ways. Merging is what turns that
// into one report entry — and the merge step is the last place a verified
// finding can be lost, so every branch here is about NOT losing one.

