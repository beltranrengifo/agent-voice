/**
 * The event stream drops. Does the adapter come back?
 *
 * A plugin that quietly stops listening is indistinguishable from a working
 * one until you notice it went silent an hour ago — which is exactly how this
 * was found. So: end the stream, then send another answer, and require it to
 * be spoken.
 */
import { writeFileSync, chmodSync, readFileSync, rmSync, mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

const dir = mkdtempSync(join(tmpdir(), "agent-voice-reconnect-"))
const spoken = join(dir, "spoken.txt")
const fake = join(dir, "voice")
writeFileSync(fake, `#!/bin/sh\ncat >> ${spoken}\nprintf "\\n--END--\\n" >> ${spoken}\n`)
chmodSync(fake, 0o755)
writeFileSync(spoken, "")

process.env.VOICE_CLI = fake
process.env.VOICE_QUIET_MS = "200"
const m = await import(new URL("../adapters/opencode.js", import.meta.url).href)

let subscriptions = 0

const ctx = {
  command: { transform: async () => {} },
  event: {
    subscribe: () => {
      const attempt = ++subscriptions
      return {
        async *[Symbol.asyncIterator]() {
          if (attempt === 1) {
            // First connection: one answer, then the stream dies mid-session.
            yield { type: "session.text.delta", data: { sessionID: "s1", delta: "Antes del corte." } }
            yield { type: "session.execution.succeeded", data: { sessionID: "s1" } }
            await new Promise((r) => setTimeout(r, 500))
            throw new Error("stream dropped")
          }
          // Reconnected: a later answer must still be read.
          yield { type: "session.text.delta", data: { sessionID: "s2", delta: "Despues del corte." } }
          yield { type: "session.execution.succeeded", data: { sessionID: "s2" } }
          await new Promise((r) => setTimeout(r, 4000))
        },
      }
    },
  },
}

const cleanup = await m.default.setup(ctx)
await new Promise((r) => setTimeout(r, 3500))
if (cleanup) await cleanup()

const out = readFileSync(spoken, "utf8")
rmSync(dir, { recursive: true, force: true })

const fail = (msg) => { console.error("FAIL:", msg); process.exit(1) }

if (subscriptions < 2) fail(`subscribed ${subscriptions} time(s) — it never reconnected after the stream dropped`)
if (!out.includes("Antes del corte")) fail("the answer before the drop was not spoken")
if (!out.includes("Despues del corte")) fail("nothing was spoken after reconnecting — the plugin went quiet for good")

console.log(`ok — reconnected (${subscriptions} subscriptions), spoke before and after the drop`)
