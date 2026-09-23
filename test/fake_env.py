"""A throwaway agent-voice installation that records what was spoken.

Every bug this project hit was in the wiring, not the speech engine, and each
one survived a check that could not have caught it. So the tests here run the
real scripts against fake Piper and player binaries and assert on what those
binaries received — if a test passes, audio really would have been produced.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class FakeInstall:
    """Temporary VOICE_HOME with stub binaries standing in for Piper and afplay."""

    def __init__(self, voice="es_ES-test-medium", **config):
        self.dir = Path(tempfile.mkdtemp(prefix="agent-voice-test-"))
        self.spoken = self.dir / "spoken.txt"
        self.played = self.dir / "played.txt"
        self.voice = voice

        (self.dir / "voices").mkdir()
        (self.dir / f"voices/{voice}.onnx").write_text("stub model")
        (self.dir / f"voices/{voice}.onnx.json").write_text(json.dumps({"num_speakers": 1}))

        # Stub Piper: record the text it was asked to say, emit a token WAV.
        venv = self.dir / "venv" / "bin"
        venv.mkdir(parents=True)
        piper = venv / "python"
        piper.write_text(
            "#!/bin/sh\n"
            f'cat >> "{self.spoken}"\n'
            f'printf "\\n--SPOKEN--\\n" >> "{self.spoken}"\n'
            'out=""\n'
            'while [ $# -gt 0 ]; do\n'
            '  case "$1" in --output-file) shift; out="$1";; esac\n'
            '  shift\n'
            'done\n'
            '[ -n "$out" ] && printf "RIFF....WAVE" > "$out"\n'
            "exit 0\n"
        )
        piper.chmod(0o755)

        # Stub player: record that playback was actually reached.
        player = self.dir / "play"
        player.write_text(f'#!/bin/sh\necho "played $*" >> "{self.played}"\nexit 0\n')
        player.chmod(0o755)

        cfg = {
            "enabled": True,
            "voice_es": voice,
            "voice_en": voice,
            "player": str(player),
        }
        cfg.update(config)
        (self.dir / "config.json").write_text(json.dumps(cfg))

    @property
    def env(self):
        e = dict(os.environ)
        e["VOICE_HOME"] = str(self.dir)
        e.pop("CLAUDE_VOICE_HOME", None)
        return e

    def run_hook(self, payload, timeout=20):
        """Feed a Stop-hook payload to the Claude Code adapter, as Claude Code does."""
        before = len(self.utterances)
        proc = subprocess.run(
            [sys.executable, str(REPO / "adapters" / "claude-code.py")],
            input=json.dumps(payload).encode(),
            env=self.env, capture_output=True, timeout=timeout,
        )
        self.settle(before)
        return proc

    def run_codex(self, event, timeout=20):
        before = len(self.utterances)
        proc = subprocess.run(
            [sys.executable, str(REPO / "adapters" / "codex.py"), json.dumps(event)],
            env=self.env, capture_output=True, timeout=timeout,
        )
        self.settle(before)
        return proc

    def run_cli(self, *args, stdin=None, timeout=20):
        before = len(self.utterances)
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "voicectl.py"), *args],
            input=(stdin.encode() if stdin is not None else None),
            env=self.env, capture_output=True, timeout=timeout,
        )
        self.settle(before)
        return proc

    def settle(self, before=0, seconds=4.0):
        """Speech happens in a detached worker; wait for THIS call to land.

        Waiting for any output at all would return instantly on a second call,
        so a duplicate answer could slip through unnoticed. Wait for the count
        to grow past `before`, and for playback to be reached — a test that only
        checked synthesis would pass on an install that never makes a sound.
        """
        import time
        deadline = time.time() + seconds
        while time.time() < deadline:
            if len(self.utterances) > before and self.playbacks:
                return
            time.sleep(0.1)

    @property
    def utterances(self):
        """Everything Piper was asked to say, one entry per call."""
        try:
            raw = self.spoken.read_text()
        except FileNotFoundError:
            return []
        return [u.strip() for u in raw.split("--SPOKEN--") if u.strip()]

    @property
    def playbacks(self):
        try:
            return self.played.read_text().strip().splitlines()
        except FileNotFoundError:
            return []

    def transcript(self, entries):
        """Write a Claude Code session transcript and return its path."""
        path = self.dir / "transcript.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        return str(path)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def assistant(*texts, tools=False):
    content = [{"type": "text", "text": t} for t in texts]
    if tools:
        content.append({"type": "tool_use", "id": "t1", "name": "Bash", "input": {}})
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def user(text="hola"):
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool_result():
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}
