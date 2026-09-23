/**
 * OpenCode adapter — drop this in ~/.config/opencode/plugin/
 *
 * OpenCode fires `session.idle` when the agent stops, but the event carries no
 * text, so we ask the client for the session's last assistant message and pipe
 * it into `voice speak`.
 *
 * Set VOICE_CLI if the CLI is not on your PATH.
 */
import type { Plugin } from "@opencode-ai/plugin"

const VOICE_CLI = process.env.VOICE_CLI ?? "voice"

export const VoicePlugin: Plugin = async ({ client, $ }) => {
  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return

      const sessionID = (event as any).properties?.sessionID
      if (!sessionID) return

      try {
        const { data: messages } = await client.session.messages({
          path: { id: sessionID },
        })
        if (!messages?.length) return

        // Newest assistant message that actually carries text.
        for (let i = messages.length - 1; i >= 0; i--) {
          const msg: any = messages[i]
          if (msg.info?.role !== "assistant") continue
          const text = (msg.parts ?? [])
            .filter((p: any) => p.type === "text" && p.text?.trim())
            .map((p: any) => p.text)
            .join("\n")
          if (!text.trim()) continue
          await $`${VOICE_CLI} speak`.stdin(text).quiet()
          return
        }
      } catch {
        // Never let a speech failure disturb the session.
      }
    },
  }
}
