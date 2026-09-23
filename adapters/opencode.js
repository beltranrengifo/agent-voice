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

/** Events that can mark the end of an answer, across OpenCode versions. */
const END_EVENTS = new Set(["session.execution.succeeded", "session.idle"])

/** How long the text stream must stay quiet before we read the answer. */
const QUIET_MS = Number(process.env.VOICE_QUIET_MS ?? 900)

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

const speak = (text, sessionID) =>
  runVoice(sessionID ? ["speak", "--session", sessionID] : ["speak"], text)

/**
 * Subcommands the slash command may run. Anything unrecognised falls back to
 * reporting status: a stray word in a prompt must never be able to turn speech
 * off behind the user's back, which is a failure that looks exactly like the
 * tool breaking.
 */
const ALLOWED = new Set([
  "status", "on", "off", "pause", "resume", "stop", "speed", "volume",
  "max", "voices", "test", "doctor", "es", "en", "speaker", "try",
])

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
    const timers = new Map()

    /** Speak a session's buffer once the answer has stopped growing. */
    function schedule(sessionID) {
      if (!sessionID) return
      clearTimeout(timers.get(sessionID))
      timers.set(
        sessionID,
        setTimeout(() => {
          timers.delete(sessionID)
          const text = buffers.get(sessionID)
          buffers.delete(sessionID)
          if (text && text.trim()) speak(text, sessionID)
        }, QUIET_MS),
      )
    }

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
            const verb = args[0]?.toLowerCase()
            await runVoice(verb && ALLOWED.has(verb) ? args : ["status"])
          },
        })
      })
    } catch {
      // Older hosts may not expose command registration; speech still works.
    }

    // The event stream can drop — a service restart, a keepalive timeout — and
    // a plugin that simply stops listening looks identical to one that works
    // until you notice it went quiet an hour ago. Reconnect instead.
    void (async () => {
      let backoff = 1000
      while (!controller.signal.aborted) {
        try {
          for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
            backoff = 1000 // a delivered event means the stream is healthy
            if (event.type === "session.text.delta") {
              const { sessionID, delta } = event.data
              if (delta) {
                buffers.set(sessionID, (buffers.get(sessionID) ?? "") + delta)
                clearTimeout(timers.get(sessionID))
                timers.delete(sessionID)
              }
              continue
            }
            if (END_EVENTS.has(event.type)) {
              // A turn that uses tools ends several executions, each of which
              // would otherwise speak its own fragment and cut off the previous
              // one, leaving only the last paragraph audible. Wait for the
              // stream to go quiet instead, then read the whole answer once.
              schedule(event.data?.sessionID)
            }
          }
        } catch {
          // Torn down, or the stream failed. The loop below decides which.
        }
        if (controller.signal.aborted) break
        await new Promise((r) => setTimeout(r, backoff))
        backoff = Math.min(backoff * 2, 30000)
      }
    })()

    return () => {
      controller.abort()
      for (const t of timers.values()) clearTimeout(t)
      timers.clear()
      buffers.clear()
    }
  },
}
