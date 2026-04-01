#!/usr/bin/env bash
PROJECT="$HOME/____your-folder-repo-stt-cursor____"
PID_FILE="/tmp/stt-cursor.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")"
    rm -f "$PID_FILE"
    notify-send -t 1500 -i microphone-sensitivity-muted "Диктовка" "Остановлена"
else
    # Для варианта Б (свой скрипт):
    "$PROJECT/.venv/bin/python" "$PROJECT/stt.py" &

    # Для варианта А (nerd-dictation) замените строку выше на:
    # "$PROJECT/.venv/bin/python" "$PROJECT/nerd-dictation/nerd-dictation" begin \
    #     --vosk-model-dir="$PROJECT/model" --continuous &

    notify-send -t 1500 -i audio-input-microphone "Диктовка" "Запущена"
fi