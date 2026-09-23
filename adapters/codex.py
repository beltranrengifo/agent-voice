#!/usr/bin/env python3
"""Codex CLI adapter — wired through the `notify` setting.

Add to ~/.codex/config.toml:

    notify = ["python3", "/absolute/path/to/adapters/codex.py"]

Codex passes a single JSON argument and, unlike Claude Code, includes the text
outright, so there is no transcript to parse.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import vlib  # noqa: E402


def main():
    if len(sys.argv) < 2:
        return
    try:
        event = json.loads(sys.argv[1])
    except Exception:
        return

    if event.get("type") != "agent-turn-complete":
        return

    # Codex spells its payload keys with hyphens; accept both in case that
    # changes, since the cost of being wrong here is total silence.
    text = event.get("last-assistant-message") or event.get("last_assistant_message")
    if text and text.strip():
        vlib.speak_async(text)


if __name__ == "__main__":
    main()
