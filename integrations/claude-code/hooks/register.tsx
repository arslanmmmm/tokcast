// tokcast-buddy: a small character in the band above the prompt box. Clicking it
// runs `tokcast predict` on the draft and shows the estimate in a speech bubble.
// Local only: the draft goes to a local process on stdin, never to the network.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Bubble } from '../types'
import { firstLine, parse } from './bubble'

const bubble = atom({ plugin: 'tokcast-buddy', key: 'bubble' } as const, {
  kind: 'idle',
} as Bubble)

const FACES: Record<Bubble['kind'], string> = {
  idle: '(•ᴗ•)',
  thinking: '(•_•)…',
  answer: '(•o•)',
  error: '(•︵•)',
}

// Runs tokcast on the draft and puts the result in the bubble.
async function estimate($: EngineInterface, command: string[], home: string): Promise<void> {
  const { text } = await $.prompt.read()
  if (text.trim() === '') {
    await update($, bubble, (): Bubble => ({ kind: 'error', lines: ['Type a prompt first, then ask me.'] }))
    return
  }

  await update($, bubble, (): Bubble => ({ kind: 'thinking' }))
  let next: Bubble
  try {
    // "-" makes tokcast read the prompt from stdin, so no length or quoting limits.
    const result = await $.process.run([...command, 'predict', '-', '--json', '--no-compare'], {
      stdin: text,
      env: home ? { TOKCAST_HOME: home } : undefined,
      timeoutMs: 20_000,
    })
    if (result.exitCode !== 0) {
      next = { kind: 'error', lines: [`tokcast failed: ${firstLine(result.stderr || result.stdout)}`] }
    } else {
      const { lines, ok } = parse(result.stdout)
      next = { kind: ok ? 'answer' : 'error', lines }
    }
  } catch {
    next = {
      kind: 'error',
      lines: [
        `Couldn't run "${command.join(' ')}".`,
        'Install tokcast (uv tool install tokcast) or set this mod\'s "command" option.',
      ],
    }
  }
  await update($, bubble, () => next)
}

export const register: Register = (on, options) => {
  const command = String(options.command ?? 'tokcast').split(/\s+/).filter(Boolean)
  const home = String(options.tokcastHome ?? '')

  // A sent prompt makes the old estimate stale. Never block the prompt on this.
  on('prompt.submit', ($, e, next) => {
    update($, bubble, (): Bubble => ({ kind: 'idle' })).catch(() => undefined)
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) {
      return next(e)
    }

    const state = await read($, bubble)
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
            onPress={() => (isBusy ? undefined : estimate($, command, home))}
          />
          {state.kind === 'answer' || state.kind === 'error' ? (
            <Button
              key="dismiss"
              label="×"
              onPress={() => update($, bubble, (): Bubble => ({ kind: 'idle' }))}
            />
          ) : null}
        </Box>
        {state.kind === 'answer' || state.kind === 'error'
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
