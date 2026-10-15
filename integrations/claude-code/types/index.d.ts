// What the speech bubble shows. `lines` are plain text, already formatted.
export type Bubble =
  | { kind: 'idle' }
  | { kind: 'thinking' }
  | { kind: 'answer'; lines: string[] }
  | { kind: 'error'; lines: string[] }

declare module 'claude-code' {
  interface PluginState {
    'tokcast-buddy': { bubble: Bubble }
  }
}
