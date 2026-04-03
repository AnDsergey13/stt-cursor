#!/usr/bin/env python3
"""Диктовка через Google SODA (offline) — gasr.

SODA (Speech On-Device API) из ChromeOS / Android.
Автопунктуация, заглавные, цифры — из коробки.
Вставка — xclip → xdotool (адаптивно для терминалов).
"""

import atexit
import io
import re
import signal
import subprocess
import sys
import os
import time

# ─── Константы ──────────────────────────────────────────────────
SAMPLE_RATE = 16000
PID_FILE = "/tmp/stt-cursor.pid"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GASR_DIR = os.path.join(BASE_DIR, "gasr")
GASR_PY = os.path.join(GASR_DIR, "gasr.py")

# WM_CLASS терминальных эмуляторов (lowercase)
TERMINAL_CLASSES = {
    "xfce4-terminal", "gnome-terminal-server", "konsole", "alacritty",
    "kitty", "terminator", "tilix", "urxvt", "rxvt", "xterm",
    "st-256color", "st", "wezterm-gui", "ghostty", "foot", "sakura",
    "lxterminal", "mate-terminal", "terminology", "qterminal",
    "cool-retro-term", "guake", "tilda", "yakuake", "tabby", "hyper",
}


# ─── Вставка текста ─────────────────────────────────────────────
def _is_terminal_focused() -> bool:
    try:
        wm_class = (
            subprocess.check_output(
                ["xdotool", "getactivewindow", "getwindowclassname"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
            .lower()
        )
        return wm_class in TERMINAL_CLASSES or "term" in wm_class
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def paste_text(text: str) -> None:
    """Вставить текст через буфер обмена (адаптивно для терминалов)."""
    subprocess.run(
        ["xclip", "-selection", "clipboard"],
        input=text.encode("utf-8"),
        check=True,
    )
    time.sleep(0.03)
    key = "ctrl+shift+v" if _is_terminal_focused() else "ctrl+v"
    subprocess.run(["xdotool", "key", key], check=True)


# ─── Постобработка ──────────────────────────────────────────────
# SODA сама ставит запятые, точки, заглавные, преобразует цифры.
# Здесь — только явные голосовые команды, которые SODA выводит текстом.
PUNCT_MAP = {
    "восклицательный знак": "!",
    "вопросительный знак": "?",
    "точка с запятой": ";",       # ← ДО «точка» и «запятая»!
    "точка": ".",
    "запятая": ",",
    "двоеточие": ":",
    "тире": " — ",
    "дефис": "-",
    "новая строка": "\n",
    "новый абзац": "\n\n",
    "открыть скобку": "(",
    "закрыть скобку": ")",
}

# Сортируем по длине фразы (длинные первыми),
# чтобы «точка с запятой» матчилась раньше «точка».
_PUNCT_PATTERNS = sorted(
    [
        (re.compile(re.escape(phrase), re.IGNORECASE), sym)
        for phrase, sym in PUNCT_MAP.items()
    ],
    key=lambda x: len(x[0].pattern),
    reverse=True,
)


def process_text(text: str) -> str:
    """Заменить голосовые команды пунктуации на символы."""
    for pat, sym in _PUNCT_PATTERNS:
        text = pat.sub(sym, text)
    # Убрать пробелы перед знаками препинания
    text = re.sub(r'\s+([.,!?:;)\]"])', r"\1", text)
    # Убрать пробелы после открывающих знаков
    text = re.sub(r'([(\["])\s+', r"\1", text)
    # Множественные пробелы → один
    text = re.sub(r"  +", " ", text)
    return text.strip()


# ─── Управление процессами ───────────────────────────────────────
_children: list[subprocess.Popen] = []


def _cleanup():
    """Завершить дочерние процессы, убрать PID-файл."""
    for p in _children:
        try:
            p.terminate()
        except Exception:
            pass
    for p in _children:
        try:
            p.wait(timeout=2)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


atexit.register(_cleanup)


def _on_sigterm(signum, frame):
    sys.exit(0)  # → atexit._cleanup()


# ─── Основной цикл ──────────────────────────────────────────────
def main():
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    signal.signal(signal.SIGTERM, _on_sigterm)

    if not os.path.isfile(GASR_PY):
        print(f"✗ Не найден: {GASR_PY}")
        print("  Запустите ./setup.sh")
        sys.exit(1)

    print("🎙 Запуск SODA...")

    # ── Pipeline: parec (захват звука) → gasr.py (распознавание) ──
    try:
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
    except FileNotFoundError:
        print("✗ parec не найден. Установите pulseaudio или pipewire-pulse.")
        sys.exit(1)

    gasr = subprocess.Popen(
        [os.path.join(GASR_DIR, "ld-linux.so"), "/usr/bin/python3", "-u", GASR_PY],
        stdin=parec.stdout,
        stdout=subprocess.PIPE,
        stderr=None,
        cwd=GASR_DIR,
    )

    parec.stdout.close()    # SIGPIPE → parec, если gasr умрёт
    _children.extend([parec, gasr])

    # ── Обёртка stdout с newline="\n" ──
    # gasr.py шлёт partial-результаты с end='\r', final — с '\n'.
    # С newline="\n" readline() разделяет ТОЛЬКО по \n,
    # а \r (partials) накапливаются в буфере.
    # Из склеенной строки "* partial\r* partial2\r* final\n"
    # берём последний сегмент после \r — финальный результат.
    gasr_out = io.TextIOWrapper(
        gasr.stdout, encoding="utf-8", errors="replace", newline="\n",
    )

    print("✅ Говорите...")

    try:
        while True:
            raw_line = gasr_out.readline()
            if not raw_line:                    # gasr завершился
                rc = gasr.poll()
                if rc and rc != 0:
                    print(f"✗ gasr.py завершился с кодом {rc}")
                break

            # "* partial\r* partial2\r* final\n" → "* final"
            line = raw_line.split("\r")[-1].strip()

            # Финальные результаты: строки вида «* распознанный текст»
            if not line.startswith("*"):
                continue

            text = line[1:].strip()         # убрать «*» и пробелы
            if not text:
                continue

            text = process_text(text)
            if text:
                paste_text(text + " ")
                print(f"  → {text}")

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()