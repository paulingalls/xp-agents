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

test('it opens by scoping the review, with exactly one agent', async () => {
  const { calls } = await runWorkflow(SCRIPT, {
    args: ARGS,
    agent: async () => scopeReply(),
  })
  assert.strictEqual(calls.length, 1)
  assert.strictEqual(calls[0].opts.label, 'scope')
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
