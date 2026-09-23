#!/usr/bin/env python3
"""agent-voice control CLI.

Usable both as the backend for the /voice slash command and directly from a
shell (`voice stop`) when you need to cut playback without waiting a turn.
"""

import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vlib  # noqa: E402

USAGE = """agent-voice — your coding agent reads its answers aloud (Piper, local, offline)

  voice setup [NAME...]    one-time install: virtualenv, Piper, and voice models
  voice doctor             diagnose a broken setup
  voice                    show status
  voice on | off           enable / disable persistently
  voice pause [DURATION]   stay enabled but keep quiet (e.g. 20m, 2h; bare = until resume)
  voice resume             start speaking again
  voice stop               cut the audio playing right now
  voice es NAME            set the Spanish voice
  voice en NAME            set the English voice
  voice speaker [es|en] ID pick the speaker on a multi-speaker voice (id or label, e.g. M/F)
  voice try NAME [ID]      audition a voice without changing your settings
  voice speed N            speaking rate (1.0 normal, 1.2 faster)
  voice volume N           volume multiplier (1.0 normal)
  voice max N              max characters spoken per answer
  voice voices             list installed voices
  voice install NAME...    download voices from HuggingFace
  voice test [TEXT]        speak a sample with the current settings
"""

DUR = re.compile(r"^(\d+(?:\.\d+)?)\s*([smh]?)$", re.I)


def parse_duration(s):
    m = DUR.match(s.strip())
    if not m:
        return None
    n = float(m.group(1))
    return n * {"": 60, "s": 1, "m": 60, "h": 3600}[m.group(2).lower()]


def fmt_remaining(cfg):
    pu = cfg.get("paused_until", 0)
    if pu == -1:
        return "paused (until you resume)"
    if pu and time.time() < pu:
        left = int(pu - time.time())
        return f"paused ({left // 60}m {left % 60}s left)"
    return None


def describe(cfg, lang):
    name = cfg[f"voice_{lang}"]
    spk = vlib.speaker_map(name)
    if not spk:
        return name
    sid = cfg.get(f"speaker_{lang}", 0)
    label = next((k for k, v in spk.items() if v == sid), "?")
    return f"{name}  speaker {sid} ({label})  [available: {', '.join(f'{k}={v}' for k, v in spk.items())}]"


def status(cfg):
    if not cfg.get("enabled", True):
        state = "OFF"
    else:
        state = fmt_remaining(cfg) or "ON (speaking)"
    lines = [
        f"agent-voice: {state}",
        f"  Spanish voice : {describe(cfg, 'es')}",
        f"  English voice : {describe(cfg, 'en')}",
        f"  speed         : {cfg['speed']}   volume: {cfg['volume']}   max chars: {cfg['max_chars']}",
    ]
    missing = [
        f"{k}={cfg[k]}" for k in ("voice_es", "voice_en")
        if not vlib.voice_path(cfg[k]).exists()
    ]
    if missing:
        lines.append(f"  MISSING voice files: {', '.join(missing)}  (run: voice install NAME)")
    return "\n".join(lines)


DEFAULT_VOICES = ["es_ES-sharvard-medium", "en_US-lessac-high"]


def setup(args):
    """Create the Piper virtualenv and fetch the default voices. Idempotent."""
    voices = args or DEFAULT_VOICES
    log = []

    venv_dir = vlib.HOME / "venv"
    if vlib.PIPER.exists():
        log.append(f"venv already present at {venv_dir}")
    else:
        log.append(f"Creating virtualenv at {venv_dir} ...")
        vlib.HOME.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return "\n".join(log + ["FAILED to create venv:", proc.stderr[-800:]])

    log.append("Installing piper-tts (this pulls onnxruntime, ~60 MB) ...")
    proc = subprocess.run(
        [str(vlib.PIPER), "-m", "pip", "install", "--upgrade", "-q", "piper-tts"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return "\n".join(log + ["FAILED to install piper-tts:", proc.stderr[-1200:]])
    log.append("piper-tts ready.")

    missing = [v for v in voices if not vlib.voice_path(v).exists()]
    if missing:
        log.append(f"Downloading voices: {', '.join(missing)} ...")
        vlib.VOICES_DIR.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [str(vlib.PIPER), "-m", "piper.download_voices",
             "--download-dir", str(vlib.VOICES_DIR), *missing],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return "\n".join(log + ["FAILED to download voices:", proc.stderr[-1200:]])
    log.append(f"Voices installed: {', '.join(vlib.installed_voices())}")

    cfg = vlib.load_config()
    cfg["enabled"] = True   # running setup is an explicit request for speech
    installed = vlib.installed_voices()
    for lang, prefix in (("es", "es_"), ("en", "en_")):
        if vlib.voice_path(cfg[f"voice_{lang}"]).exists():
            continue
        # Prefer a voice for the right language; otherwise take any installed
        # one. Leaving a name that points at nothing means that language is
        # silently never spoken.
        match = next((v for v in installed if v.startswith(prefix)), None) or \
            (installed[0] if installed else None)
        if match:
            cfg[f"voice_{lang}"] = match
            cfg[f"speaker_{lang}"] = 0
            if not match.startswith(prefix):
                log.append(f"No {lang} voice installed; using {match} for it too.")
    vlib.save_config(cfg)

    ok, problems = vlib.is_ready()
    log.append("")
    log.append("Setup complete." if ok else "Setup finished with problems:")
    log.extend(f"  - {p}" for p in problems)
    log.append("")
    log.append(status(cfg))
    if ok:
        log.append("\nTry it:  voice test")
    return "\n".join(log)


def doctor():
    ok, problems = vlib.is_ready()
    lines = ["agent-voice doctor", ""]
    lines.append(f"  home          : {vlib.HOME}")
    lines.append(f"  piper python  : {vlib.PIPER} {'OK' if vlib.PIPER.exists() else 'MISSING'}")
    lines.append(f"  voices dir    : {vlib.VOICES_DIR} ({len(vlib.installed_voices())} installed)")
    player = vlib.find_player()
    lines.append(f"  audio player  : {' '.join(player) if player else 'NONE FOUND'}")
    err = vlib.RUN_DIR / "last-error.log"
    if err.exists():
        lines.append(f"  last error    : {err}")
        lines.append("    " + err.read_text(errors="replace").strip()[-400:].replace("\n", "\n    "))
    lines.append("")
    if ok:
        lines.append("  All good.")
    else:
        lines.extend(f"  PROBLEM: {p}" for p in problems)
        lines.append("\n  Run: voice setup")
    return "\n".join(lines)


def install(names):
    if not names:
        return "Give at least one voice name, e.g. es_ES-sharvard-medium"
    vlib.VOICES_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(vlib.PIPER), "-m", "piper.download_voices",
         "--download-dir", str(vlib.VOICES_DIR), *names],
        capture_output=True, text=True,
    )
    out = (proc.stdout + proc.stderr).strip().splitlines()
    tail = "\n".join(out[-6:])
    return f"{tail}\n\nInstalled: {', '.join(vlib.installed_voices())}"


def speak_now(cfg, text, voice=None, speaker=None):
    lang = vlib.detect_lang(text)
    if voice is None:
        voice = cfg["voice_en"] if lang == "en" else cfg["voice_es"]
        speaker = cfg.get("speaker_en" if lang == "en" else "speaker_es", 0)
    if not vlib.voice_path(voice).exists():
        return f"Voice file missing: {voice}. Run: voice install {voice}"
    vlib.stop_playback(everywhere=True)
    vlib.RUN_DIR.mkdir(parents=True, exist_ok=True)
    wav = vlib.RUN_DIR / "test.wav"
    proc = subprocess.run(
        vlib.piper_cmd(voice, cfg, wav, speaker or 0),
        input=text.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        return f"Piper failed:\n{proc.stderr.decode()[-500:]}"
    play_cmd = vlib.find_player()
    if not play_cmd:
        return "No audio player found (looked for afplay, paplay, aplay, ffplay)."
    # Record the player so `voice stop` from another shell can cut it short.
    player = subprocess.Popen(play_cmd + [str(wav)], start_new_session=True)
    vlib.PID_FILE.write_text(str(player.pid))
    try:
        player.wait()
    except KeyboardInterrupt:
        player.terminate()
    finally:
        try:
            if vlib.PID_FILE.read_text().strip() == str(player.pid):
                vlib.PID_FILE.unlink()
        except Exception:
            pass
    spk = vlib.speaker_map(voice)
    label = next((k for k, v in spk.items() if v == (speaker or 0)), None)
    extra = f" speaker {speaker or 0}" + (f" ({label})" if label else "") if spk else ""
    return f"Played with {voice}{extra} (detected: {lang})."


def main(argv):
    cfg = vlib.load_config()
    cmd = (argv[0].lower() if argv else "status")
    args = argv[1:]

    if cmd in ("-h", "--help", "help"):
        return USAGE + "\n" + status(cfg)

    if cmd == "speak":
        # The portable entry point: any agent that can pipe its final message
        # into this speaks through the same pipeline Claude Code uses.
        session = None
        if args and args[0] == "--session":
            session = args[1] if len(args) > 1 else None
            args = args[2:]
        text = " ".join(args) if args else sys.stdin.read()
        reason = vlib.speak_async(text, cfg, session=session)
        return f"Not spoken: {reason}" if reason else "Speaking."

    if cmd == "setup":
        return setup(args)

    if cmd in ("doctor", "check"):
        return doctor()

    if cmd == "status":
        ok, problems = vlib.is_ready()
        out = status(cfg)
        if not ok:
            out += "\n\nNOT SET UP YET:\n" + "\n".join(f"  - {p}" for p in problems)
            out += "\n  Run: voice setup"
        return out + "\n\nRun `voice help` for all commands."

    if cmd == "on":
        cfg["enabled"] = True
        cfg["paused_until"] = 0
        vlib.save_config(cfg)
        return status(cfg)

    if cmd == "off":
        cfg["enabled"] = False
        vlib.save_config(cfg)
        vlib.stop_playback(everywhere=True)
        return status(cfg)

    if cmd == "pause":
        if args:
            secs = parse_duration(args[0])
            if secs is None:
                return f"Bad duration: {args[0]} (use 30s, 20m, 2h)"
            cfg["paused_until"] = time.time() + secs
        else:
            cfg["paused_until"] = -1
        vlib.save_config(cfg)
        vlib.stop_playback(everywhere=True)
        return status(cfg)

    if cmd == "resume":
        cfg["paused_until"] = 0
        cfg["enabled"] = True
        vlib.save_config(cfg)
        return status(cfg)

    if cmd == "stop":
        # An explicit request for quiet covers every session, not just this one.
        return "Playback stopped." if vlib.stop_playback(everywhere=True) else "Nothing was playing."

    if cmd in ("es", "en"):
        if not args:
            return f"Current {cmd} voice: {cfg['voice_' + cmd]}\nInstalled: {', '.join(vlib.installed_voices()) or 'none'}"
        name = args[0]
        if not vlib.voice_path(name).exists():
            msg = install([name])
            if not vlib.voice_path(name).exists():
                return f"Could not install {name}.\n{msg}"
        cfg[f"voice_{cmd}"] = name
        # A new model has its own speaker ids; fall back to 0 unless one is given.
        spk = vlib.speaker_map(name)
        if len(args) > 1 and spk:
            sid = spk.get(args[1], spk.get(args[1].upper()))
            if sid is None:
                try:
                    sid = int(args[1])
                except ValueError:
                    sid = 0
            cfg[f"speaker_{cmd}"] = sid if sid in spk.values() else 0
        else:
            cfg[f"speaker_{cmd}"] = 0
        vlib.save_config(cfg)
        return status(cfg)

    if cmd == "try":
        if not args:
            return "Give a voice name, e.g. voice try es_ES-sharvard-medium F"
        name = args[0]
        if not vlib.voice_path(name).exists():
            install([name])
            if not vlib.voice_path(name).exists():
                return f"Could not install {name}."
        spk = vlib.speaker_map(name)
        sid = 0
        if len(args) > 1 and spk:
            sid = spk.get(args[1], spk.get(args[1].upper()))
            if sid is None:
                try:
                    sid = int(args[1])
                except ValueError:
                    sid = 0
        sample = "Hola. Así es como sonarán las respuestas de Claude Code con esta voz." \
            if name.startswith("es") else \
            "Hello. This is how Claude Code answers will sound with this voice."
        return speak_now(cfg, sample, voice=name, speaker=sid)

    if cmd in ("speaker", "spk"):
        lang = "es"
        rest = list(args)
        if rest and rest[0].lower() in ("es", "en"):
            lang = rest.pop(0).lower()
        spk = vlib.speaker_map(cfg[f"voice_{lang}"])
        if not spk:
            return f"{cfg[f'voice_{lang}']} is single-speaker; nothing to choose."
        if not rest:
            return f"{describe(cfg, lang)}\nSet with: voice speaker {lang} <id or label>"
        want = rest[0]
        sid = spk.get(want, spk.get(want.upper()))
        if sid is None:
            try:
                sid = int(want)
            except ValueError:
                return f"Unknown speaker {want}. Available: {', '.join(f'{k}={v}' for k, v in spk.items())}"
        if sid not in spk.values():
            return f"Speaker {sid} out of range. Available: {', '.join(f'{k}={v}' for k, v in spk.items())}"
        cfg[f"speaker_{lang}"] = sid
        vlib.save_config(cfg)
        return status(cfg)

    if cmd in ("speed", "volume"):
        if not args:
            return f"{cmd} = {cfg[cmd]}"
        try:
            val = float(args[0].replace(",", "."))
        except ValueError:
            return f"{cmd} needs a number, got: {args[0]}"
        if not 0.3 <= val <= 3.0:
            return f"{cmd} must be between 0.3 and 3.0"
        cfg[cmd] = val
        vlib.save_config(cfg)
        return status(cfg)

    if cmd in ("max", "maxchars", "max_chars"):
        if not args:
            return f"max_chars = {cfg['max_chars']}"
        try:
            cfg["max_chars"] = max(0, int(args[0]))
        except ValueError:
            return f"max needs an integer, got: {args[0]}"
        vlib.save_config(cfg)
        return status(cfg)

    if cmd == "voices":
        have = vlib.installed_voices()
        return ("Installed voices:\n  " + "\n  ".join(have) if have else "No voices installed.") + \
            "\n\nBrowse and listen: https://rhasspy.github.io/piper-samples/\nInstall with: voice install NAME"

    if cmd == "install":
        return install(args)

    if cmd == "test":
        text = " ".join(args) if args else (
            "Listo. Esta es la voz que va a leerte las respuestas de Claude Code."
        )
        return speak_now(cfg, text)

    return f"Unknown command: {cmd}\n\n{USAGE}"


if __name__ == "__main__":
    # Detached playback child, spawned by vlib.speak_async().
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        vlib.run_worker(sys.argv[2])
    else:
        print(main(sys.argv[1:]))
