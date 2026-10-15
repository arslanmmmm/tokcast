// Builds the `tokcast predict` command line from what the session knows.
// Pure, so the tests can check every case without an engine.

export type SessionFacts = {
  contextTokens?: number // the live context window; absent in a fresh session
  model?: string // e.g. "claude-opus-5-5"
  effort?: string // last effort seen on a model request; absent before the first turn
}

const MODEL_FAMILY = /opus|sonnet|haiku|fable/
const EFFORTS = new Set(['low', 'medium', 'high', 'xhigh', 'max'])

export function predictArgs(command: readonly string[], facts: SessionFacts): string[] {
  // "-" makes tokcast read the prompt from stdin, so no length or quoting limits.
  const argv = [...command, 'predict', '-', '--json', '--no-compare']

  // No reading yet means nothing has been sent: tokcast's "new chat" default is right.
  if (facts.contextTokens !== undefined && facts.contextTokens > 0) {
    argv.push('--context', String(Math.round(facts.contextTokens)))
  }
  // Only pass what tokcast knows; otherwise let it use its default and say so.
  const family = facts.model?.toLowerCase().match(MODEL_FAMILY)?.[0]
  if (family) argv.push('--model', family)
  if (facts.effort && EFFORTS.has(facts.effort)) argv.push('--effort', facts.effort)

  return argv
}
