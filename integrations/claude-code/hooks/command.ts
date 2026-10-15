// What `/tokcast ...` asks for. Pure, so the tests can check every case.

import type { View } from '../types'

export type { View }

export type Command =
  | { action: 'view'; view: View }
  | { action: 'predict'; text: string }
  | { action: 'help' }

const VIEWS: Record<string, View> = { show: 'full', hide: 'mini', off: 'off' }

export function parseCommand(args: string): Command {
  const text = args.trim()
  if (text === '' || text === 'help') return { action: 'help' }
  const view = VIEWS[text.toLowerCase()]
  return view ? { action: 'view', view } : { action: 'predict', text }
}

export const HELP = [
  '/tokcast <prompt>   estimate a prompt here, even when the band is busy',
  '/tokcast show       show the character with its button',
  '/tokcast hide       shrink it to just the face (click the face to open it)',
  '/tokcast off        hide it completely (/tokcast show brings it back)',
].join('\n')

export const VIEW_MESSAGES: Record<View, string> = {
  full: 'tokcast is shown above the prompt.',
  mini: 'tokcast is shrunk to its face. Click it to open.',
  off: 'tokcast is hidden. /tokcast show brings it back.',
}

export function isView(value: unknown): value is View {
  return value === 'full' || value === 'mini' || value === 'off'
}
