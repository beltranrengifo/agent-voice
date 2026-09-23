---
description: Control the spoken-answer plugin (stop/pause/on/off/voice/speed/setup)
argument-hint: "[stop | pause 20m | resume | on | off | es NAME | en NAME | speaker M | speed 1.2 | voices | try NAME | test | setup | doctor]"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/voicectl.py:*)
---

!`"${CLAUDE_PLUGIN_ROOT}/scripts/voicectl.py" $ARGUMENTS`

The command above already ran and its output is shown. Relay it to the user in
one short line, in the language they are writing in — just confirm what changed.
Do not repeat the block verbatim, do not add commentary, and do not call any
tool: the action is already done.
