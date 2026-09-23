#!/usr/bin/env python3
"""Stop-hook entrypoint: read the last assistant message and speak it.

The hook must return immediately, so synthesis and playback happen in a
detached child process group that this script re-executes as `--worker`.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vlib  # noqa: E402


def worker(text_file):
    """Detached: synthesize `text_file` to WAV and play it."""
    # Popen(start_new_session=True) already made us a session leader; calling
    # setsid() again raises EPERM, so only do it if we somehow are not one.
    try:
        if os.getpid() != os.getsid(0):
            os.setsid()
    except OSError:
        pass
    vlib.RUN_DIR.mkdir(parents=True, exist_ok=True)
    vlib.PID_FILE.write_text(str(os.getpid()))

    try:
        payload = json.loads(Path(text_file).read_text())
        text = payload["text"]
        cfg = payload["cfg"]
        voice = payload["voice"]

        wav = vlib.RUN_DIR / "out.wav"
        cmd = vlib.piper_cmd(voice, cfg, wav, payload.get("speaker", 0))
        proc = subprocess.run(
            cmd, input=text.encode(), stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0 or not wav.exists():
            (vlib.RUN_DIR / "last-error.log").write_bytes(proc.stderr[-4000:])
            return
        player = vlib.find_player()
        if not player:
            (vlib.RUN_DIR / "last-error.log").write_text("No audio player found.")
            return
        subprocess.run(player + [str(wav)])
    except Exception as exc:  # never let the worker die noisily
        try:
            (vlib.RUN_DIR / "last-error.log").write_text(repr(exc))
        except Exception:
            pass
    finally:
        try:
            Path(text_file).unlink()
        except Exception:
            pass
        try:
            if vlib.PID_FILE.read_text().strip() == str(os.getpid()):
                vlib.PID_FILE.unlink()
        except Exception:
            pass


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        worker(sys.argv[2])
        return

    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        return

    cfg = vlib.load_config()
    if vlib.is_silenced(cfg):
        return

    # Avoid speaking again when a Stop hook re-entered our own continuation.
    if hook_input.get("stop_hook_active"):
        return

    transcript = hook_input.get("transcript_path")
    if not transcript:
        return

    raw = vlib.last_assistant_text(transcript)
    if not raw.strip():
        return

    text = vlib.clean_for_speech(raw, int(cfg.get("max_chars", 1200)))
    if len(text) < 2:
        return

    lang = vlib.detect_lang(text)
    voice = cfg.get("voice_en" if lang == "en" else "voice_es")
    speaker = cfg.get("speaker_en" if lang == "en" else "speaker_es", 0)
    if not vlib.voice_path(voice).exists():
        return

    # Whatever is playing is now stale — the newer answer wins.
    vlib.stop_playback()

    vlib.RUN_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(vlib.RUN_DIR), suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump({"text": text, "cfg": cfg, "voice": voice, "speaker": speaker}, fh)

    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--worker", tmp],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )


if __name__ == "__main__":
    main()
