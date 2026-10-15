// What the speech bubble shows. `lines` are plain text, already formatted.
export type Bubble =
  | { kind: 'idle' }
  | { kind: 'thinking' }
  | { kind: 'answer'; lines: string[] }
  | { kind: 'error'; lines: string[] }

// How the character shows above the prompt: full = face, button and answer;
// mini = just the face (click to open); off = nothing. See hooks/command.ts.
export type View = 'full' | 'mini' | 'off'

declare module 'claude-code' {
  interface PluginState {
    'tokcast-buddy': { bubble: Bubble; effort: string; view: View }
  }
}
