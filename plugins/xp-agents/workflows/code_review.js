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

return {
  level: LEVEL,
  summary: `Scoped ${scope.files.length} changed files. ${scope.summary}`,
  findings: [],
  stats: { ...baseStats(), pluginRoot: Boolean(PLUGIN_ROOT) },
}
