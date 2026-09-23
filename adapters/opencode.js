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
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"

/**
 * Resolve the controller without trusting PATH.
 *
 * OpenCode's background service runs with a minimal environment, so `voice`
 * is typically not resolvable there even when it works in your shell. The
 * package ships scripts/voicectl.py alongside this file, so call that through
 * an interpreter we can name outright.
 */
function resolveCommand() {
  if (process.env.VOICE_CLI) return [process.env.VOICE_CLI]

  const script = fileURLToPath(new URL("../scripts/voicectl.py", import.meta.url))
  if (existsSync(script)) {
    for (const python of ["/usr/bin/python3", "/opt/homebrew/bin/python3", "python3"]) {
      if (python === "python3" || existsSync(python)) return [python, script]
    }
  }
  return ["voice"] // last resort: hope it is on PATH
}

const COMMAND = resolveCommand()

function runVoice(args, input) {
  return new Promise((resolve) => {
    try {
      const child = spawn(COMMAND[0], [...COMMAND.slice(1), ...args], {
        stdio: [input === undefined ? "ignore" : "pipe", "ignore", "ignore"],
        detached: input !== undefined,
      })
      child.on("error", () => resolve())
      if (input !== undefined) {
        child.stdin.end(input)
        child.unref()
        resolve()
        return
      }
      child.on("exit", () => resolve())
    } catch {
      resolve()
    }
  })
}

const speak = (text) => runVoice(["speak"], text)

/** Pull the plain text the user typed out of a command invocation. */
function promptText(prompt) {
  if (!prompt) return ""
  if (typeof prompt === "string") return prompt
  const parts = prompt.parts ?? prompt.content ?? prompt
  if (!Array.isArray(parts)) return ""
  return parts
    .map((p) => (typeof p === "string" ? p : (p?.text ?? "")))
    .join(" ")
}

export default {
  id: "agent-voice",
  setup: async (ctx) => {
    const controller = new AbortController()
    // Assistant prose per session, accumulated as it streams in.
    const buffers = new Map()

    // /voice — same subcommands as the CLI (stop, pause, on, off, speed...).
    try {
      await ctx.command.transform((editor) => {
        editor.add({
          name: "voice",
          description: "Control spoken answers: stop, pause, resume, on, off, speed, es, en",
          execute: async ({ prompt }) => {
            const args = promptText(prompt)
              .replace(/^\/?voice\b/, "")
              .trim()
              .split(/\s+/)
              .filter(Boolean)
            await runVoice(args.length ? args : ["status"])
          },
        })
      })
    } catch {
      // Older hosts may not expose command registration; speech still works.
    }

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
