# claude-voice

Claude Code reads its answers out loud in your terminal.

Speech is synthesized locally with [Piper](https://github.com/OHF-Voice/piper1-gpl):
nothing leaves your machine, it works offline, and there is no API bill. It
picks a Spanish or English voice automatically based on what the answer is
written in, and it does not read code out loud.

## What it actually does

A `Stop` hook fires when Claude finishes a turn. It reads the last prose from
the session transcript, strips everything unpleasant to hear, and hands the
result to a detached worker that synthesizes and plays it — so the hook returns
in milliseconds and never blocks your terminal.

What gets stripped: fenced code blocks, inline code, markdown tables, URLs and
file paths. Sentences that lose too much to that stripping are dropped entirely
rather than read as fragments — "the check uses instead of , see the file line
42" is worse than silence.

On a 2024 MacBook, 6.6 seconds of audio takes about 1 second to generate, model
loading included. No background daemon is needed.

## Requirements

- Python 3.9+ (3.14 works; `onnxruntime` ships wheels for it)
- macOS, or Linux with one of `paplay`, `aplay`, `ffplay` installed

## Install

```sh
claude plugin marketplace add beltranrengifo/claude-voice
claude plugin install claude-voice@claude-voice
```

Restart Claude Code, then run the one-time setup, which creates a virtualenv,
installs Piper and downloads the default voices (about 170 MB) into
`~/.claude/voice`:

```
/voice setup
```

That is all. The next answer Claude gives will be spoken.

### Optional: the shell CLI

Everything is reachable through `/voice` inside Claude Code. If you also want it
from a plain shell, link the script onto your `PATH`:

```sh
ln -sf ~/.claude/plugins/cache/claude-voice/claude-voice/*/scripts/voicectl.py ~/.local/bin/voice
```

## Usage

| Command | Effect |
| --- | --- |
| `/voice` | Show current status |
| `/voice stop` | Cut the audio playing right now |
| `/voice pause [20m]` | Stay enabled but keep quiet; bare form lasts until `resume` |
| `/voice resume` | Start speaking again |
| `/voice on` / `/voice off` | Enable or disable persistently |
| `/voice es NAME [SPEAKER]` | Set the Spanish voice |
| `/voice en NAME [SPEAKER]` | Set the English voice |
| `/voice speaker [es\|en] ID` | Pick the speaker on a multi-speaker model |
| `/voice try NAME [ID]` | Audition a voice without changing settings |
| `/voice speed N` | Speaking rate (1.0 normal, 1.2 faster) |
| `/voice volume N` | Volume multiplier |
| `/voice max N` | Max characters spoken per answer |
| `/voice voices` | List installed voices |
| `/voice install NAME...` | Download more voices |
| `/voice test [TEXT]` | Speak a sample |
| `/voice setup` | One-time install |
| `/voice doctor` | Diagnose a broken setup |

`off` and `pause` differ on purpose: `off` disables the plugin until you turn it
back on, `pause` keeps it armed but silent, optionally for a fixed period.

Sending any message also cuts playback immediately, via a `UserPromptSubmit`
hook — so you rarely need `/voice stop` at all. There is no push-to-talk
interruption: you cannot cut the voice by speaking, only by typing.

## Choosing a voice

Browse and listen at <https://rhasspy.github.io/piper-samples/>, then install by
name:

```
/voice install es_MX-claude-high
/voice es es_MX-claude-high
```

Some models hold several speakers. `es_ES-sharvard-medium` has `M=0` and `F=1`,
selected with `/voice speaker es F`.

Worth knowing before you pick: `es_ES` has no `high`-quality model, its ceiling
is `medium`. The `high` Spanish voices are Latin American
(`es_MX-claude-high`) or Argentine (`es_AR-daniela-high`), so you are choosing
between a peninsular accent at medium quality and a Latin American one at high.

## Configuration

State lives in `~/.claude/voice/config.json` and persists across sessions.
Editing it by hand works; the CLI is a safer front end. Set `CLAUDE_VOICE_HOME`
to move the whole thing elsewhere.

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

Add a `"player"` key if the audio player autodetection guesses wrong, for
example `"player": "ffplay -nodisp -autoexit -loglevel quiet"`.

## Limitations

- One-way. No barge-in: you cannot interrupt by speaking.
- Only Spanish and English are detected; other languages fall back to Spanish.
- Detection is a stopword vote, so a short answer mixing both languages can pick
  the wrong voice.
- Voice models are not in this repo. `/voice setup` downloads them from
  Hugging Face.

## License

MIT. Piper and the voice models carry their own licenses — most voices are
CC-BY or similar, listed on each model's card in the
[piper-voices](https://huggingface.co/rhasspy/piper-voices) repository.
