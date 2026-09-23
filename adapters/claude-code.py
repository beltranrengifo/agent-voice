#!/usr/bin/env python3
"""Claude Code adapter — wired as a `Stop` hook.

Claude Code hands the hook a JSON object on stdin but not the message itself,
so we dig the last prose out of the session transcript.
"""

import json
import sys
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

    text = vlib.last_assistant_text(transcript)
    if text.strip():
        vlib.speak_async(text)


if __name__ == "__main__":
    main()
