#!/usr/bin/env python3
"""Диктовка через Google SODA (offline) — gasr.

SODA (Speech On-Device API) из ChromeOS / Android.
Автопунктуация, заглавные, цифры — из коробки.
Вставка — xclip → xdotool (адаптивно для терминалов).
"""

import argparse
import atexit
import io
import json
import re
import signal
import subprocess
import sys
import os
import tempfile
import threading
import time
from datetime import datetime

from term_fixer import fix_text

# ─── Константы ──────────────────────────────────────────────────
SAMPLE_RATE = 16000
PID_FILE = "/tmp/stt-cursor.pid"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GASR_DIR = os.path.join(BASE_DIR, "gasr")
GASR_PY = os.path.join(GASR_DIR, "gasr.py")
HISTORY_DIR = os.path.join(BASE_DIR, "history")

# WM_CLASS терминальных эмуляторов (lowercase)
TERMINAL_CLASSES = {
    "xfce4-terminal", "gnome-terminal-server", "konsole", "alacritty",
    "kitty", "terminator", "tilix", "urxvt", "rxvt", "xterm",
    "st-256color", "st", "wezterm-gui", "ghostty", "foot", "sakura",
    "lxterminal", "mate-terminal", "terminology", "qterminal",
    "cool-retro-term", "guake", "tilda", "yakuake", "tabby", "hyper",
}


# ─── Починка зависшего BT-микрофона ─────────────────────────────
# После простоя wireplumber усыпляет BT-источник, а при пробуждении
# SCO-транспорт гарнитуры зависает: pipewire показывает RUNNING, но
# байты не идут, SODA пишет «Pipeline lagging» и молчит навсегда.


def _notify(title: str, message: str) -> None:
    """Показать десктопное уведомление (best effort)."""
    try:
        subprocess.run(
            ["notify-send", "-t", "5000", title, message],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass


# ─── История диктовки ───────────────────────────────────────────
def _history_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _history_warning(message: str) -> None:
    print(f"⚠ {message}")
    _notify("🎙 Диктовка", message)


class DictationHistory:
    """Хранить исходные и итоговые финалы в JSONL-файле сессии."""

    def __init__(self, directory: str, enabled: bool = True, on_warning=None):
        self.directory = directory
        self.enabled = enabled
        self.path = None
        self._file = None
        self._warned = False
        self._on_warning = on_warning or _history_warning
        if not enabled:
            return

        try:
            os.makedirs(directory, exist_ok=True)
            now = datetime.now().astimezone()
            self._file = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=directory,
                prefix=now.strftime("session-%Y%m%d-%H%M%S-"),
                suffix=".jsonl",
                delete=False,
            )
            self.path = self._file.name
        except OSError as error:
            self._fail(error)
            return

        self._write({
            "type": "session_start",
            "timestamp": _history_timestamp(),
            "pid": os.getpid(),
        })

    def _write(self, data: dict) -> None:
        if not self.enabled or self._file is None:
            return
        try:
            self._file.write(json.dumps(data, ensure_ascii=False) + "\n")
            self._file.flush()
        except OSError as error:
            self._fail(error)

    def _fail(self, error: OSError) -> None:
        self.enabled = False
        file = self._file
        self._file = None
        if file is not None:
            try:
                file.close()
            except OSError:
                pass
        if not self._warned:
            self._warned = True
            self._on_warning(
                f"Не удалось записать историю в {self.directory}: {error}. "
                "Запись истории отключена до перезапуска."
            )

    def record(self, soda_text: str, final_text: str) -> None:
        """Записать пару «исходный финал SODA → вставленный текст»."""
        self._write({
            "type": "segment",
            "timestamp": _history_timestamp(),
            "soda": soda_text,
            "final": final_text,
        })

    def close(self) -> None:
        """Закрыть файл истории; повторный вызов безопасен."""
        self.enabled = False
        file = self._file
        self._file = None
        if file is None:
            return
        try:
            file.close()
        except OSError as error:
            self._fail(error)


_history: DictationHistory | None = None


def _default_source_is_bluetooth() -> bool:
    """True, если дефолтный источник — BT-микрофон (bluez_input).

    При просмотре видео через гарнитуру (профиль A2DP) источника
    bluez_input нет, и дефолтом становится другой микрофон — трогать
    BT-профиль в этом случае нельзя, иначе оборвётся воспроизведение.
    """
    try:
        out = subprocess.check_output(
            ["pactl", "get-default-source"], stderr=subprocess.DEVNULL,
        )
        return out.decode().strip().startswith("bluez_input")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _kick_bluetooth_mic() -> bool:
    """Передёрнуть профиль BT-карты (off → headset-head-unit).

    Оживляет зависший SCO-транспорт без переподключения гарнитуры.
    """
    try:
        out = subprocess.check_output(
            ["pactl", "--format=json", "list", "cards"],
            stderr=subprocess.DEVNULL,
        )
        cards = json.loads(out)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return False
    kicked = False
    for card in cards:
        name = card.get("name", "")
        if not name.startswith("bluez_card"):
            continue
        try:
            subprocess.run(
                ["pactl", "set-card-profile", name, "off"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            pass    # карта могла уже быть в off
        time.sleep(2)
        try:
            subprocess.run(
                ["pactl", "set-card-profile", name, "headset-head-unit"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            return False
        time.sleep(3)   # дождаться поднятия SCO-транспорта
        kicked = True
    return kicked


def _other_capture_active() -> bool:
    """True, если с BT-микрофона пишет кто-то ещё (звонок, браузер)."""
    try:
        sources = json.loads(subprocess.check_output(
            ["pactl", "--format=json", "list", "sources"],
            stderr=subprocess.DEVNULL,
        ))
        outputs = json.loads(subprocess.check_output(
            ["pactl", "--format=json", "list", "source-outputs"],
            stderr=subprocess.DEVNULL,
        ))
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return True     # не смогли проверить — карту не трогаем
    bluez = {
        s.get("index") for s in sources
        if s.get("name", "").startswith("bluez_input")
    }
    for out in outputs:
        if out.get("source") not in bluez:
            continue
        props = out.get("properties", {})
        if props.get("application.name") == "WirePlumber":
            continue
        if props.get("application.process.binary") == "wireplumber":
            continue
        return True     # чужой захват — профиль не переключаем
    return False


def _restore_bt_output() -> None:
    """Вернуть bluez-карте A2DP-профиль после остановки диктовки.

    Если SCO-транспорт сбоил, wireplumber может оставить карту в off или
    headset-head-unit — тогда наушники пропадают из микшера как выход.
    """
    if not _default_source_is_bluetooth() or _other_capture_active():
        return
    try:
        cards = json.loads(subprocess.check_output(
            ["pactl", "--format=json", "list", "cards"],
            stderr=subprocess.DEVNULL,
        ))
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return
    for card in cards:
        name = card.get("name", "")
        if not name.startswith("bluez_card"):
            continue
        profile = str(card.get("active_profile", ""))
        if profile.startswith("a2dp"):
            continue    # уже профиль для прослушивания
        profiles = card.get("profiles", {})
        target = next(
            (p for p in ("a2dp-sink", "a2dp-sink-sbc")
             if profiles.get(p, {}).get("available") in (True, "yes")),
            None,
        )
        if target is None:
            continue
        try:
            subprocess.run(
                ["pactl", "set-card-profile", name, target],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            pass    # карта могла уйти в off или исчезнуть


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
    """Завершить дочерние процессы, убрать PID-файл и закрыть историю."""
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
    # Если пайплайн работал, вернуть наушникам профиль для прослушивания:
    # после сбоя SCO wireplumber может оставить карту в off, и выход
    # пропадает из микшера («звук отвалился» после остановки диктовки).
    if _children:
        _restore_bt_output()
    # Удаляем PID-файл, только если он наш: при быстром стоп/старте
    # новый экземпляр уже мог записать туда свой PID.
    try:
        with open(PID_FILE) as f:
            if f.read().strip() == str(os.getpid()):
                os.remove(PID_FILE)
    except FileNotFoundError:
        pass
    if _history is not None:
        _history.close()


atexit.register(_cleanup)


def _on_sigterm(signum, frame):
    sys.exit(0)  # → atexit._cleanup()


# ─── Пайплайн: parec (захват звука) → gasr.py (распознавание) ────
def _start_pipeline():
    """Запустить parec → gasr, вернуть (gasr, обёртку его stdout)."""
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
        stderr=subprocess.PIPE,
        cwd=GASR_DIR,
    )

    parec.stdout.close()    # SIGPIPE → parec, если gasr умрёт
    _children[:] = [parec, gasr]

    # ── Обёртка stdout с newline="\n" ──
    # gasr.py шлёт partial-результаты с end='\r', final — с '\n'.
    # С newline="\n" readline() разделяет ТОЛЬКО по \n,
    # а \r (partials) накапливаются в буфере.
    # Из склеенной строки "* partial\r* partial2\r* final\n"
    # берём последний сегмент после \r — финальный результат.
    gasr_out = io.TextIOWrapper(
        gasr.stdout, encoding="utf-8", errors="replace", newline="\n",
    )
    return gasr, gasr_out


def _watch_stderr(gasr, restart_event, state):
    """Переливать stderr gasr в лог; при зависании починить и перезапустить.

    Признак зависшего BT-транспорта — «Pipeline lagging» сразу после
    старта: в рабочих сессиях этой строки не бывает никогда. Лечение:
    передёрнуть BT-профиль (только если диктовка идёт через BT-микрофон,
    иначе оборвётся воспроизведение в гарнитуре) и перезапустить пайплайн.
    """
    for raw in iter(gasr.stderr.readline, b""):
        line = raw.decode("utf-8", "replace")
        sys.stderr.write(line)
        if restart_event.is_set() or state["finals"] > 0:
            continue        # рестарт уже запрошен / сбой не на старте
        if "Pipeline lagging" in line:
            print("⚠ Распознавание зависло (нет звука с микрофона), перезапускаю...")
            _notify("🎙 Диктовка", "Микрофон завис, перезапускаю…")
            restart_event.set()
            for p in _children:
                try:
                    p.terminate()
                except Exception:
                    pass
            if _default_source_is_bluetooth():
                _kick_bluetooth_mic()
            return


# ─── Основной цикл ──────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Офлайн-диктовка через Google SODA")
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="не записывать историю сессии в history/",
    )
    return parser.parse_args()


def main():
    global _history
    args = _parse_args()

    # Лог писать построчно: stdout уходит в файл, и без этого сообщения
    # видны только при завершении процесса — отладка вслепую.
    sys.stdout.reconfigure(line_buffering=True)

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    signal.signal(signal.SIGTERM, _on_sigterm)

    if not os.path.isfile(GASR_PY):
        print(f"✗ Не найден: {GASR_PY}")
        print("  Запустите ./setup.sh")
        sys.exit(1)

    # gasr.py работает под системным /usr/bin/python3 и требует protobuf.
    # Ставить только через pacman: pip-установка теряется при мажорном
    # обновлении Python (смена site-packages), и диктовка молча сломается.
    probe = subprocess.run(
        ["/usr/bin/python3", "-c", "import google.protobuf"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode != 0:
        print("✗ /usr/bin/python3: не найден модуль google.protobuf")
        print("  Установите: sudo pacman -S python-protobuf")
        print("  (через pip ставить нельзя — теряется при обновлении Python)")
        sys.exit(1)

    _history = DictationHistory(HISTORY_DIR, enabled=not args.no_history)
    if _history.enabled:
        print(f"📝 История: {_history.path}")
    else:
        print("📝 История диктовки отключена")

    print("🎙 Запуск SODA...")

    # ── Цикл с авторестартом: если watchdog поймал зависание
    # («Pipeline lagging»), пайплайн перезапускается ──
    restart_event = threading.Event()
    state = {"finals": 0}
    restarts = 0
    while True:
        gasr, gasr_out = _start_pipeline()
        watchdog = threading.Thread(
            target=_watch_stderr,
            args=(gasr, restart_event, state),
            daemon=True,
        )
        watchdog.start()

        print("✅ Говорите...")

        try:
            while True:
                raw_line = gasr_out.readline()
                if not raw_line:                    # gasr завершился
                    rc = gasr.poll()
                    if rc and rc != 0 and not restart_event.is_set():
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

                soda_text = text
                text = process_text(text)
                text = fix_text(text)
                if text:
                    inserted_text = text + " "
                    paste_text(inserted_text)
                    if _history is not None:
                        _history.record(soda_text, inserted_text)
                    state["finals"] += 1
                    print(f"  → {text}")

        except KeyboardInterrupt:
            break

        if not restart_event.is_set():
            break
        watchdog.join()         # дождаться окончания починки
        restart_event.clear()
        restarts += 1
        if restarts > 2:
            print("✗ Микрофон не отвечает — переподключите гарнитуру")
            _notify("🎙 Диктовка", "Микрофон не отвечает — переподключите гарнитуру")
            break


if __name__ == "__main__":
    main()