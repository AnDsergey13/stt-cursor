#!/usr/bin/env bash

# --- Настройки ---
PROJECT="$HOME/____your-folder-repo-stt-cursor____"
PID_FILE="/tmp/stt-cursor.pid"
LOG="/tmp/stt-cursor.log"

# --- Окружение для горячей клавиши ---
export DISPLAY="${DISPLAY:-:0}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# --- Лог для отладки ---
echo "=== $(date) ===" >> "$LOG"
echo "PID_FILE exists: $(test -f "$PID_FILE" && echo yes || echo no)" >> "$LOG"
echo "PID_FILE content: $(cat "$PID_FILE" 2>/dev/null)" >> "$LOG"

stop_dictation() {
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null
        echo "Killed $pid" >> "$LOG"
    fi
    rm -f "$PID_FILE"
    notify-send -t 1500 "Диктовка" "Остановлена" 2>>"$LOG"
}

start_dictation() {
    "$PROJECT/.venv/bin/python" "$PROJECT/main.py" >> "$LOG" 2>&1 &
    echo $! > "$PID_FILE"
    disown
    echo "Started PID: $!" >> "$LOG"
    notify-send -t 1500 "Диктовка" "Запущена" 2>>"$LOG"
}

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ACTION: stop" >> "$LOG"
    stop_dictation
else
    echo "ACTION: start" >> "$LOG"
    rm -f "$PID_FILE"
    start_dictation
fi