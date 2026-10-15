// tokcast-buddy: a small character in the band above the prompt box. Clicking it
// runs `tokcast predict` on the draft and shows the estimate in a speech bubble.
// Local only: the draft goes to a local process on stdin, never to the network.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Bubble } from '../types'
import { predictArgs, statuslinePayload, usedNow } from './args'
import type { RateLimit } from './args'
import { firstLine, parse } from './bubble'

const bubble = atom({ plugin: 'tokcast-buddy', key: 'bubble' } as const, {
  kind: 'idle',
} as Bubble)
// The session's effort as the last main-loop model request carried it.
const effort = atom({ plugin: 'tokcast-buddy', key: 'effort' } as const, '')

const FACES: Record<Bubble['kind'], string> = {
  idle: '(•ᴗ•)',
  thinking: '(•_•)…',
  answer: '(•o•)',
  error: '(•︵•)',
}

type Config = { command: string[]; home: string; autoIngest: boolean }

// DuckDB allows one writing process at a time, so this mod's tokcast calls run
// one after another, never side by side.
let queue: Promise<unknown> = Promise.resolve()

// Runs one tokcast command (e.g. ['predict', ...]) after the ones already queued.
async function runTokcast($: EngineInterface, cfg: Config, args: string[], stdin: string) {
  const run = queue.then(() =>
    $.process.run([...cfg.command, ...args], {
      stdin,
      env: cfg.home ? { TOKCAST_HOME: cfg.home } : undefined,
      timeoutMs: 60_000,
    }),
  )
  queue = run.catch(() => undefined)
  return run
}

// Saves the live 5h and weekly readings, so tokcast can learn tokens -> % of limit.
async function recordReadings($: EngineInterface, cfg: Config, limits: readonly RateLimit[]) {
  if (limits.length === 0) return // an API-key session has no usage windows
  const payload = statuslinePayload(limits, await $.session.id())
  if (payload) await runTokcast($, cfg, ['statusline'], payload)
}

// After a turn: save a reading, then ingest the new logs so the next estimate
// and the calibration both include that turn. A separate TOKCAST_HOME (e.g. the
// synthetic demo) is never fed the real logs.
async function refresh($: EngineInterface, cfg: Config): Promise<void> {
  const { rateLimits } = await $.session.usage()
  await recordReadings($, cfg, rateLimits)
  if (cfg.autoIngest && !cfg.home) await runTokcast($, cfg, ['ingest'], '')
}

// Runs tokcast on the draft and puts the result in the bubble.
async function estimate($: EngineInterface, cfg: Config): Promise<void> {
  const { text } = await $.prompt.read()
  if (text.trim() === '') {
    await update($, bubble, (): Bubble => ({ kind: 'error', lines: ['Type a prompt first, then ask me.'] }))
    return
  }

  await update($, bubble, (): Bubble => ({ kind: 'thinking' }))
  const { context, rateLimits } = await $.session.usage()
  const argv = predictArgs([], {
    contextTokens: context.tokens,
    model: await $.session.model(),
    effort: (await read($, effort)) || undefined,
  })
  let next: Bubble
  try {
    await recordReadings($, cfg, rateLimits)
    const result = await runTokcast($, cfg, argv, text)
    if (result.exitCode !== 0) {
      next = { kind: 'error', lines: [`tokcast failed: ${firstLine(result.stderr || result.stdout)}`] }
    } else {
      const { lines, ok } = parse(result.stdout, usedNow(rateLimits))
      next = { kind: ok ? 'answer' : 'error', lines }
    }
  } catch {
    next = {
      kind: 'error',
      lines: [
        `Couldn't run "${cfg.command.join(' ')}".`,
        'Install tokcast (uv tool install tokcast) or set this mod\'s "command" option.',
      ],
    }
  }
  await update($, bubble, () => next)
}

export const register: Register = (on, options) => {
  const cfg: Config = {
    command: String(options.command ?? 'tokcast').split(/\s+/).filter(Boolean),
    home: String(options.tokcastHome ?? ''),
    autoIngest: options.autoIngest !== false,
  }

  // Readings and logs change after every turn. The work runs on a timer, outside
  // this hook's dispatch, so it never delays the turn's end.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    $.clock.after(0, () => {
      refresh($, cfg).catch(() => undefined)
    })
    return result
  })

  // Effort isn't on $.session, so remember it from the main loop's requests.
  // turn.step streams the model's reply: pass every chunk through untouched.
  on('turn.step', async function* ($, e, next) {
    if (!e.agentId && typeof e.effort === 'string') {
      const level = e.effort
      update($, effort, () => level).catch(() => undefined)
    }
    return yield* next(e)
  })

  // A sent prompt makes the old estimate stale. Never block the prompt on this.
  on('prompt.submit', ($, e, next) => {
    update($, bubble, (): Bubble => ({ kind: 'idle' })).catch(() => undefined)
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) {
      return next(e)
    }

    // State outlives a reload; a shape from another version must not break the band.
    const saved = await read($, bubble)
    const state: Bubble = saved && saved.kind in FACES ? saved : { kind: 'idle' }
    const { Box, Button, Text } = $.ui.resolve(e)
    const isBusy = state.kind === 'thinking'

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" gap={1}>
          <Text bold color="cyan">
            {FACES[state.kind]}
          </Text>
          <Button
            key="estimate"
            label={isBusy ? 'Thinking...' : 'How much will this cost?'}
            onPress={() => (isBusy ? undefined : estimate($, cfg))}
          />
          {state.kind === 'answer' || state.kind === 'error' ? (
            <Button
              key="dismiss"
              label="×"
              onPress={() => update($, bubble, (): Bubble => ({ kind: 'idle' }))}
            />
          ) : null}
        </Box>
        {(state.kind === 'answer' || state.kind === 'error') && Array.isArray(state.lines)
          ? state.lines.map((line, i) => (
              <Text dimColor={i > 0} color={state.kind === 'error' ? 'red' : undefined}>
                {'  '}
                {line}
              </Text>
            ))
          : null}
      </Box>
    )
  })
}
