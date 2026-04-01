#!/usr/bin/env python3
"""Непрерывная диктовка: Vosk → xclip → вставка (адаптивная)."""

import json
import subprocess
import signal
import sys
import os
import time

from vosk import Model, KaldiRecognizer

SAMPLE_RATE = 16000
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model")
PID_FILE = "/tmp/stt-cursor.pid"

# WM_CLASS терминальных эмуляторов (lowercase).
# Если ваш терминал отсутствует — добавьте его сюда.
# Узнать класс окна: xdotool getactivewindow getwindowclassname
TERMINAL_CLASSES = {
    "xfce4-terminal", "gnome-terminal-server", "konsole", "alacritty",
    "kitty", "terminator", "tilix", "urxvt", "rxvt", "xterm",
    "st-256color", "st", "wezterm-gui", "ghostty", "foot", "sakura",
    "lxterminal", "mate-terminal", "terminology", "qterminal",
    "cool-retro-term", "guake", "tilda", "yakuake", "tabby", "hyper",
}


def _is_terminal_focused() -> bool:
    """Проверить, является ли активное окно терминальным эмулятором."""
    try:
        wm_class = subprocess.check_output(
            ["xdotool", "getactivewindow", "getwindowclassname"],
            stderr=subprocess.DEVNULL,
        ).decode().strip().lower()

        if wm_class in TERMINAL_CLASSES:
            return True
        # Запасной вариант: имя класса содержит «term»
        if "term" in wm_class:
            return True
        return False
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def paste_text(text: str) -> None:
    """Вставить текст через буфер обмена (адаптивно для терминалов)."""
    subprocess.run(
        ["xclip", "-selection", "clipboard"],
        input=text.encode("utf-8"),
        check=True,
    )
    # Микропауза: xclip форкается для сервировки буфера —
    # даём дочернему процессу стать selection owner.
    time.sleep(0.03)

    if _is_terminal_focused():
        # Ctrl+Shift+V — вставка средствами терминального эмулятора.
        # Текст доставляется через bracketed paste, минуя баги TUI.
        subprocess.run(["xdotool", "key", "ctrl+shift+v"], check=True)
    else:
        # Обычные GUI-приложения — стандартный Ctrl+V.
        subprocess.run(["xdotool", "key", "ctrl+v"], check=True)


def process_text(text: str) -> str:
    """Постобработка: пунктуация голосом, капитализация."""
    replacements = {
        "точка": ".",
        "запятая": ",",
        "вопросительный знак": "?",
        "восклицательный знак": "!",
        "новая строка": "\n",
        "двоеточие": ":",
        "тире": " — ",
    }
    for word, symbol in replacements.items():
        text = text.replace(word, symbol)
    if text:
        text = text[0].upper() + text[1:]
    return text


def cleanup(signum=None, frame=None):
    """Убрать PID-файл при завершении."""
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass
    sys.exit(0)


def main():
    # Записать PID для toggle-скрипта
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    print(f"Загрузка модели из {MODEL_PATH}...")
    model = Model(MODEL_PATH)
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    rec.SetWords(False)

    # Запустить parec (PulseAudio/PipeWire capture)
    parec = subprocess.Popen(
        [
            "parec",
            "--rate", str(SAMPLE_RATE),
            "--channels", "1",
            "--format", "s16le",
            "--latency-msec", "100",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    print("Диктовка запущена. Говорите...")

    try:
        while True:
            data = parec.stdout.read(4000)
            if not data:
                break

            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = result.get("text", "").strip()
                if text:
                    text = process_text(text)
                    paste_text(text + " ")
                    print(f"  → {text}")
    except KeyboardInterrupt:
        pass
    finally:
        parec.terminate()
        parec.wait()
        cleanup()


if __name__ == "__main__":
    main()