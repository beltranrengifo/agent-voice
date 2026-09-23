/**
 * OpenCode adapter (v2 plugin API) — plain JavaScript, zero imports.
 *
 * `Plugin.define` in @opencode/plugin is the identity function; it exists only
 * to attach types. Shipping plain JS that exports the object directly means the
 * host has no .ts to transpile and no package to resolve, which removes the two
 * things most likely to break a plugin install.
 *
 * opencode.ts is the same code with types, kept for type-checking.
 *
 * Install:  opencode plugin add github:beltranrengifo/agent-voice
 */
import { spawn } from "node:child_process"

const VOICE_CLI = process.env.VOICE_CLI ?? "voice"

function speak(text) {
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

export default {
  id: "agent-voice",
  setup: async (ctx) => {
    const controller = new AbortController()
    // Assistant prose per session, accumulated as it streams in.
    const buffers = new Map()

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
}
