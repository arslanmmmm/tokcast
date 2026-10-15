// Turns `tokcast predict --json` output into the speech bubble's text.
// Pure functions, no engine calls, so the tests can check them directly.

// The fields of tokcast's Forecast (src/tokcast/predict/forecast.py) this mod reads.
type Estimate = {
  total: { low: number; median: number; high: number }
  level: string // "task", "all" or "prior"
  group: string // e.g. "bugfix turns"
  n: number
  limit_pct: [number, number, number] | null
}

export type Forecast = {
  classification: { task_type: string }
  context: { mode: string; tokens: number; note: string } // mode: "new chat" or "given"
  estimates: Estimate[]
  new_chat: Estimate | null // set when a fresh chat would be clearly cheaper
  limit_window: string | null
  limit_readings: number
}

// Calibration needs this many status-line readings (decision 19 in docs/plan.md).
const READINGS_NEEDED = 3

export function tokens(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`
  if (n >= 1e3) return `${Math.round(n / 1e3)}k`
  return String(Math.round(n))
}

function pct(p: number): string {
  return p < 1 ? `${p.toFixed(1)}%` : `${Math.round(p)}%`
}

// Where the context size came from, in words for the bubble.
function contextLine(f: Forecast): string {
  return f.context.mode === 'given'
    ? `this conversation: ${tokens(f.context.tokens)} tokens of context so far`
    : `new chat: ${f.context.note}`
}

// Three or four short lines: the cost, the % of the limit, the basis, and a
// hint when starting a new chat would be clearly cheaper.
export function summarize(f: Forecast): string[] {
  const e = f.estimates[0]
  if (!e) return ['tokcast returned no estimate.']

  const { low, median, high } = e.total
  const cost = `~${tokens(median)} tokens (${tokens(low)}–${tokens(high)}) for a ${f.classification.task_type} turn`

  const window = f.limit_window ?? '5h'
  const limit = e.limit_pct
    ? `≈ ${pct(e.limit_pct[1])} of your ${window} limit (${pct(e.limit_pct[0])}–${pct(e.limit_pct[2])})`
    : `% of ${window} limit: not calibrated yet (${f.limit_readings}/${READINGS_NEEDED} status-line readings)`

  // Every estimate states its basis; with no history it is an assumption.
  const basis =
    e.level === 'prior'
      ? 'basis: built-in assumption (no history yet: run tokcast ingest)'
      : `basis: ${e.n} of your ${e.group}`

  const lines = [cost, limit, `${basis} · ${contextLine(f)}`]
  if (f.new_chat) {
    lines.push(`tip: in a new chat this would be ~${tokens(f.new_chat.total.median)} tokens`)
  }
  return lines
}

// Parses stdout; a problem becomes a readable message instead of a crash.
export function parse(stdout: string): { lines: string[]; ok: boolean } {
  try {
    return { lines: summarize(JSON.parse(stdout) as Forecast), ok: true }
  } catch {
    return { lines: ["Couldn't read tokcast's output."], ok: false }
  }
}

// The first meaningful line of an error, kept short enough for the band.
export function firstLine(text: string): string {
  const line = text.split('\n').find(l => l.trim() !== '') ?? 'unknown error'
  return line.length > 120 ? `${line.slice(0, 117)}...` : line.trim()
}
