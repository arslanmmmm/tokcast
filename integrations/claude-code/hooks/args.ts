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

// A usage-limit window as $.session.usage() reports it.
export type RateLimit = { kind: string; percentUsed: number; resetsAt?: string }

const WINDOWS = new Set(['five_hour', 'seven_day'])

// The live readings in the shape of Claude Code's status-line JSON, so
// `tokcast statusline` records them with its existing, tested code.
// Null when there is nothing to record (an API-key session has no windows).
export function statuslinePayload(limits: readonly RateLimit[], sessionId: string): string | null {
  const rate_limits: Record<string, { used_percentage: number; resets_at: number }> = {}
  for (const l of limits) {
    const resets = l.resetsAt ? Date.parse(l.resetsAt) : Number.NaN
    if (WINDOWS.has(l.kind) && !Number.isNaN(resets)) {
      rate_limits[l.kind] = { used_percentage: l.percentUsed, resets_at: Math.floor(resets / 1000) }
    }
  }
  return Object.keys(rate_limits).length ? JSON.stringify({ session_id: sessionId, rate_limits }) : null
}

// The % used right now per window, for the bubble.
export function usedNow(limits: readonly RateLimit[]): { fiveHour?: number; sevenDay?: number } {
  const find = (kind: string) => limits.find(l => l.kind === kind)?.percentUsed
  return { fiveHour: find('five_hour'), sevenDay: find('seven_day') }
}
