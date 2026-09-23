#!/bin/sh
# Kill any in-flight speech. Deliberately shell, not Python: this runs on every
# prompt submit, so process startup cost has to stay near zero.
# Home resolution mirrors vlib._default_home().
VOICE_DIR="${VOICE_HOME:-$CLAUDE_VOICE_HOME}"
if [ -z "$VOICE_DIR" ]; then
    if [ -d "$HOME/.claude/voice" ]; then
        VOICE_DIR="$HOME/.claude/voice"
    else
        VOICE_DIR="$HOME/.config/agent-voice"
    fi
fi
PIDFILE="$VOICE_DIR/run/current.pid"
[ -f "$PIDFILE" ] || exit 0
PID=$(cat "$PIDFILE" 2>/dev/null)
case "$PID" in
    ''|*[!0-9]*) exit 0 ;;
esac
kill -TERM "-$PID" 2>/dev/null || kill -TERM "$PID" 2>/dev/null
rm -f "$PIDFILE"
exit 0
