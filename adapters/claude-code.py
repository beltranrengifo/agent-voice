#!/usr/bin/env python3
"""Claude Code adapter — wired as a `Stop` hook.

Claude Code hands the hook a JSON object on stdin but not the message itself,
so we dig the last prose out of the session transcript.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import vlib  # noqa: E402


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        return

    # Guard against a Stop hook that re-entered our own continuation.
    if hook_input.get("stop_hook_active"):
        return

    transcript = hook_input.get("transcript_path")
    if not transcript:
        return

    # The hook can fire a moment before the final message reaches the
    # transcript on disk, which reads as an empty turn. Give it a short grace
    # period rather than silently skipping the answer.
    text = ""
    for attempt in range(6):
        text = vlib.last_assistant_text(transcript)
        if text.strip():
            break
        time.sleep(0.25)

    if text.strip():
        vlib.speak_async(text, session=hook_input.get("session_id"))


if __name__ == "__main__":
    main()
