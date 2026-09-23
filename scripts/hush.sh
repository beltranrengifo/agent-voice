#!/bin/sh
# Kill any in-flight speech. Deliberately shell, not Python: this runs on every
# prompt submit, so process startup cost has to stay near zero.
PIDFILE="${CLAUDE_VOICE_HOME:-$HOME/.claude/voice}/run/current.pid"
[ -f "$PIDFILE" ] || exit 0
PID=$(cat "$PIDFILE" 2>/dev/null)
case "$PID" in
    ''|*[!0-9]*) exit 0 ;;
esac
kill -TERM "-$PID" 2>/dev/null || kill -TERM "$PID" 2>/dev/null
rm -f "$PIDFILE"
exit 0
