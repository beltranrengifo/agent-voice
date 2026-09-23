/**
 * OpenCode adapter — targets the v2 plugin API (@opencode/plugin 2.x).
 *
 * Install globally:
 *   mkdir -p ~/.config/opencode/plugin
 *   cp opencode.ts ~/.config/opencode/plugin/agent-voice.ts
 *
 * v2 exposes no way to read a session's message history from a plugin, so
 * instead of asking for the final text we accumulate the `session.text.delta`
 * stream as it arrives and speak what we collected when the session goes idle.
 *
 * Set VOICE_CLI if `voice` is not on your PATH.
 */
import { Plugin } from "@opencode/plugin"
import { spawn } from "node:child_process"

const VOICE_CLI = process.env.VOICE_CLI ?? "voice"

function speak(text: string): void {
  try {
    const child = spawn(VOICE_CLI, ["speak"], {
      stdio: ["pipe", "ignore", "ignore"],
      detached: true,
    })
    child.on("error", () => {})
    child.stdin.end(text)
    child.unref()
  } catch {
    // Speech is a convenience; never let it disturb the session.
  }
}

export default Plugin.define({
  id: "agent-voice",
  setup: async (ctx) => {
    const controller = new AbortController()
    // Assistant prose per session, accumulated as it streams in.
    const buffers = new Map<string, string>()

    // /voice — same subcommands as the CLI (stop, pause, on, off, speed...).
    await ctx.command.transform((editor) => {
      editor.add({
        name: "voice",
        description: "Control spoken answers: stop, pause, resume, on, off, speed, es, en",
        execute: async () => {},
      })
    })

    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          if (event.type === "session.text.delta") {
            const { sessionID, delta } = event.data
            if (delta) buffers.set(sessionID, (buffers.get(sessionID) ?? "") + delta)
            continue
          }
          if (event.type === "session.idle") {
            const { sessionID } = event.data
            const text = buffers.get(sessionID)
            buffers.delete(sessionID)
            if (text && text.trim()) speak(text)
          }
        }
      } catch {
        // Aborted on teardown, or the stream dropped. Either way, stop quietly.
      }
    })()

    return () => {
      controller.abort()
      buffers.clear()
    }
  },
})
