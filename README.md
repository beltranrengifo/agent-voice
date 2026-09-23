# agent-voice

Your coding agent reads its answers out loud in the terminal.

Speech is synthesized locally with [Piper](https://github.com/OHF-Voice/piper1-gpl):
nothing leaves your machine, it works offline, and there is no API bill. It
picks a Spanish or English voice automatically based on what the answer is
written in, and it does not read code out loud.

Works with Claude Code, Codex and OpenCode — and with anything else that can
run a command when it finishes a turn.

## What it actually does

When your agent finishes a turn, a small adapter grabs the text it just wrote,
strips everything unpleasant to hear, and hands it to a detached worker that
synthesizes and plays it. The adapter returns in milliseconds and never blocks
your terminal.

What gets stripped: fenced code blocks, inline code, markdown tables, URLs and
file paths. Sentences that lose too much to that stripping are dropped entirely
rather than read as fragments — "the check uses instead of , see the file line
42" is worse than silence.

On an M-series Mac, 6.6 seconds of audio takes about 1 second to generate, model
loading included. No background daemon is needed.

## Architecture

One engine, thin adapters. Everything agent-specific lives in `adapters/` and is
about twenty lines; the pipeline underneath is shared.

```
adapters/claude-code.py ─┐
adapters/codex.py        ├─→ voice speak ─→ clean ─→ Piper ─→ player
adapters/opencode.ts     ─┘
```

Adding an agent means writing one adapter that extracts the final message and
pipes it into `voice speak`. Nothing else changes.

| Agent | Mechanism | Gives you the text? |
| --- | --- | --- |
| Claude Code | `Stop` hook | No — the adapter reads the session transcript |
| Codex | `notify` in `config.toml` | Yes, in `last-assistant-message` |
| OpenCode | plugin, `session.text.delta` + `session.idle` | No — the adapter accumulates the stream |
| Anything else | pipe into `voice speak` | You decide |

## Requirements

- Python 3.9+ (3.14 works; `onnxruntime` ships wheels for it)
- macOS, or Linux with one of `paplay`, `aplay`, `ffplay` installed

## Install

### Claude Code

```sh
claude plugin marketplace add beltranrengifo/agent-voice
claude plugin install agent-voice@agent-voice
```

If answers are never spoken, check `/hooks`. Some builds list a plugin's hooks
without running them; in that case declare them in `~/.claude/settings.json`
instead, pointing at the installed plugin directory:

```json
{
  "hooks": {
    "Stop": [{ "hooks": [{ "type": "command",
      "command": "python3 \"$HOME/.claude/plugins/cache/agent-voice/agent-voice/<version>/adapters/claude-code.py\"" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command",
      "command": "sh \"$HOME/.claude/plugins/cache/agent-voice/agent-voice/<version>/scripts/hush.sh\"" }] }]
  }
}
```

Restart Claude Code, then run the one-time setup, which builds a virtualenv,
installs Piper and downloads the default voices (about 170 MB):

```
/speak setup
```

That is all. The next answer will be spoken.

### Codex, OpenCode, or anything else

Clone the repo and run setup once:

```sh
git clone https://github.com/beltranrengifo/agent-voice.git ~/.agent-voice
~/.agent-voice/scripts/voicectl.py setup
ln -sf ~/.agent-voice/scripts/voicectl.py ~/.local/bin/voice   # optional but handy
```

**Codex** — add to `~/.codex/config.toml`:

```toml
notify = ["python3", "/Users/YOU/.agent-voice/adapters/codex.py"]
```

**OpenCode** (v2) — one command, no file copying:

```sh
opencode plugin add github:beltranrengifo/agent-voice
```

That fetches the package, resolves `@opencode/plugin`, and adds the entry to
`~/.config/opencode/opencode.json`. Dropping a loose `.ts` file into
`~/.config/opencode/plugin/` does **not** work: `opencode plugin add` accepts
only an npm or Git specifier.

The adapter targets the v2 plugin API (`@opencode/plugin` 2.x — note the scope,
which differs from the v1 `@opencode-ai/plugin`). v2 gives plugins no way to
read a session's message history, so the adapter accumulates the
`session.text.delta` stream and speaks it when the session goes idle.

**Any other agent** — if it can run a command at end of turn, pipe the text in:

```sh
echo "$FINAL_MESSAGE" | voice speak
```

`voice speak` reads stdin, applies the same cleaning and voice selection, and
plays without blocking. That is the whole integration contract.

## Usage

Inside Claude Code use `/speak`; anywhere else use the `voice` CLI. Same
subcommands either way. (The command is `/speak`, not `/voice`, because Claude
Code already ships a built-in `/voice` for push-to-talk input.)

| Command | Effect |
| --- | --- |
| `voice` | Show current status |
| `voice stop` | Cut the audio playing right now |
| `voice pause [20m]` | Stay enabled but keep quiet; bare form lasts until `resume` |
| `voice resume` | Start speaking again |
| `voice on` / `voice off` | Enable or disable persistently |
| `voice es NAME [SPEAKER]` | Set the Spanish voice |
| `voice en NAME [SPEAKER]` | Set the English voice |
| `voice speaker [es\|en] ID` | Pick the speaker on a multi-speaker model |
| `voice try NAME [ID]` | Audition a voice without changing settings |
| `voice speed N` | Speaking rate (1.0 normal, 1.2 faster) |
| `voice volume N` | Volume multiplier |
| `voice max N` | Max characters spoken per answer |
| `voice voices` | List installed voices |
| `voice install NAME...` | Download more voices |
| `voice speak` | Speak text from stdin — the portable entry point |
| `voice test [TEXT]` | Speak a sample |
| `voice setup` | One-time install |
| `voice doctor` | Diagnose a broken setup |

`off` and `pause` differ on purpose: `off` disables it until you turn it back
on, `pause` keeps it armed but silent, optionally for a fixed period.

In Claude Code, sending any message also cuts playback immediately via a
`UserPromptSubmit` hook, so you rarely need `/speak stop`. There is no barge-in
on any agent: you cannot cut the voice by speaking, only by typing.

## Choosing a voice

Browse and listen at <https://rhasspy.github.io/piper-samples/>, then install by
name:

```
voice install es_MX-claude-high
voice es es_MX-claude-high
```

Some models hold several speakers. `es_ES-sharvard-medium` has `M=0` and `F=1`,
selected with `voice speaker es F`.

Worth knowing before you pick: `es_ES` has no `high`-quality model, its ceiling
is `medium`. The `high` Spanish voices are Latin American (`es_MX-claude-high`)
or Argentine (`es_AR-daniela-high`), so you are choosing between a peninsular
accent at medium quality and a Latin American one at high.

## Configuration

State lives in `config.json` under the data directory and persists across
sessions and across agents — configure once, every agent obeys it.

The data directory is `$VOICE_HOME` if set, otherwise `~/.claude/voice` when it
already exists (so older installs keep working), otherwise
`~/.config/agent-voice`.

```json
{
  "enabled": true,
  "voice_es": "es_ES-sharvard-medium",
  "speaker_es": 0,
  "voice_en": "en_US-lessac-high",
  "speed": 1.0,
  "max_chars": 1200
}
```

Add a `"player"` key if audio player autodetection guesses wrong, for example
`"player": "ffplay -nodisp -autoexit -loglevel quiet"`.

## Several sessions at once

Each session speaks independently and only ever interrupts itself, so finishing
a turn in one window will not cut off the answer you are listening to in
another. `voice stop` is the exception: it silences every session, because that
is what you mean by it.

Install the hook in one place only. Declaring it both in the plugin and in
`settings.json` makes every turn fire twice, and the two runs cut each other
off.

## When it goes quiet

Check `voice` first — speech being off looks exactly like the tool being
broken. Every config change is recorded, so you can see what turned it off and
when:

```sh
cat "${VOICE_HOME:-$HOME/.config/agent-voice}/run/config-changes.log"
```

Then `voice doctor` for a missing model, virtualenv or audio player.

## Limitations

- One-way. No barge-in: you cannot interrupt by speaking.
- Only Spanish and English are detected; other languages fall back to Spanish.
- Detection is a stopword vote, so a short answer mixing both languages can pick
  the wrong voice.
- Voice models are not in this repo; `voice setup` downloads them from
  Hugging Face.
- The OpenCode adapter type-checks against `@opencode/plugin` 2.0.15 and its
  event shapes are taken from that package, and `opencode plugin add` installs
  it cleanly — but it has not yet been run against a live session, unlike the
  Claude Code and Codex adapters. Note that `opencode plugin list` reports
  "No plugins found" even once installed; whether that is cosmetic is unconfirmed.
- OpenCode v1 is not supported; its plugin API differs entirely.

## Tests

```sh
./test/run.sh
```

The suite drives the real adapters against stub Piper and player binaries and
asserts on what those binaries received, so a passing test means audio really
would have come out. Checking that the code merely parses is not enough: every
bug this project shipped survived exactly that kind of check.

`test/mutation_check.py` keeps the suite honest. It reintroduces each bug that
actually shipped — the answer never read, prose before a tool call lost, code
read aloud, playback never reached, the same answer spoken twice — and fails if
the tests stay green. A suite you have not seen go red is not evidence.

## License

MIT. Piper and the voice models carry their own licenses — most voices are
CC-BY or similar, listed on each model's card in the
[piper-voices](https://huggingface.co/rhasspy/piper-voices) repository.
