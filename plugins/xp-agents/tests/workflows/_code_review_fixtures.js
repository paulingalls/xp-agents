'use strict'

// Shared fixtures for the code-review orchestrator suites.
//
// Extracted when `code_review_test.js` crossed the 500-line cap — the split its
// own ceiling entry named. Unlike the script under test, which has no module
// system and therefore cannot be split at all, this is ordinary CommonJS.
//
// Not `*_test.js`: the JS runner globs that suffix, and a fixtures file
// collected as a suite would report zero tests and pass.

const path = require('node:path')

const { runWorkflow } = require('./_workflow_harness.js')

const SCRIPT = path.join(__dirname, '..', '..', 'workflows', 'code_review.js')

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

const finderCalls = (calls) => calls.filter((c) => c.opts.phase === 'Find')
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
        if (served) return { candidates: [], angleRead: true }
        served = true
        return { candidates, angleRead: true }
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

module.exports = {
  SCRIPT, ARGS, scopeReply, finderCalls, verifyCalls, cand, runVerify, confirmAll,
}
