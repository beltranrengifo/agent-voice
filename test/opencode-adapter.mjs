// Fake `voice` CLI so the test observes what the adapter would speak.
import { writeFileSync, chmodSync, readFileSync, rmSync, mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

// A fake CLI records what the adapter would have spoken, so the test asserts
// on behaviour rather than syntax. `node --check` passes on an adapter that
// references an undefined constant; this does not.
const dir = mkdtempSync(join(tmpdir(), "agent-voice-test-"))
const spoken = join(dir, "spoken.txt")
const fake = join(dir, "voice")
writeFileSync(fake, `#!/bin/sh\ncat >> ${spoken}\nprintf "\\n--END--\\n" >> ${spoken}\n`)
chmodSync(fake, 0o755)
writeFileSync(spoken, "")

process.env.VOICE_CLI = fake
const m = await import(new URL("../adapters/opencode.js", import.meta.url).href)

const events = [
  { type: "session.text.delta", data: { sessionID: "s1", delta: "Primer parrafo. " } },
  { type: "session.execution.succeeded", data: { sessionID: "s1" } },
  { type: "session.text.delta", data: { sessionID: "s1", delta: "Segundo parrafo. " } },
  { type: "session.execution.succeeded", data: { sessionID: "s1" } },
  { type: "session.text.delta", data: { sessionID: "s1", delta: "Tercer parrafo." } },
  { type: "session.execution.succeeded", data: { sessionID: "s1" } },
]
const ctx = {
  command: { transform: async () => {} },
  event: {
    subscribe: () => ({
      async *[Symbol.asyncIterator]() {
        for (const e of events) { yield e; await new Promise(r => setTimeout(r, 120)) }
        await new Promise(r => setTimeout(r, 2500))
      },
    }),
  },
}
const cleanup = await m.default.setup(ctx)
await new Promise((r) => setTimeout(r, 3000))
if (cleanup) await cleanup()

const out = readFileSync(spoken, "utf8")
rmSync(dir, { recursive: true, force: true })

const calls = out.split("--END--").filter((c) => c.trim())
const fail = (msg) => { console.error("FAIL:", msg); process.exit(1) }

if (calls.length !== 1) fail(`spoke ${calls.length} times, expected 1 — each execution cut off the previous`)
for (const part of ["Primer parrafo", "Segundo parrafo", "Tercer parrafo"]) {
  if (!calls[0].includes(part)) fail(`missing "${part}" — only part of the answer was read`)
}
console.log("ok — one call, whole answer:", JSON.stringify(calls[0].trim()))
