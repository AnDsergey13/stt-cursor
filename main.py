#!/usr/bin/env python3
"""Двуязычная диктовка: GigaAM (русский) + Vosk (английский).

Определение языка — Whisper tiny через sherpa-onnx.
VAD — Silero через sherpa-onnx.
Вставка — xclip → xdotool (адаптивно для терминалов).
"""

import json
import subprocess
import signal
import sys
import os
import time

import numpy as np
import sherpa_onnx
from vosk import Model as VoskModel, KaldiRecognizer

# ─── Константы ──────────────────────────────────────────────────
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512          # ~32 мс при 16 кГц
MIN_SPEECH_SEC = 0.4         # Минимальная длина фразы для обработки
LANG_FALLBACK = "ru"         # Язык по умолчанию (короткие фрагменты)
LANG_MIN_SEC = 0.6           # Минимум для детекции языка (иначе → fallback)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
PID_FILE = "/tmp/stt-cursor.pid"

# Языки, акустически близкие к русскому → отправляем в GigaAM
_SLAVIC = {"ru", "uk", "be", "bg", "mk", "sr", "hr", "bs", "sl"}

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
RU_PUNCT = {
    "точка": ".",
    "запятая": ",",
    "вопросительный знак": "?",
    "восклицательный знак": "!",
    "новая строка": "\n",
    "двоеточие": ":",
    "тире": " — ",
}

EN_PUNCT = {
    "period": ".",
    "full stop": ".",
    "comma": ",",
    "question mark": "?",
    "exclamation mark": "!",
    "new line": "\n",
    "colon": ":",
    "dash": " — ",
}


def _apply_punct(text: str, table: dict) -> str:
    for word, sym in table.items():
        text = text.replace(word, sym)
    return text[0].upper() + text[1:] if text else text


def process_text(text: str, lang: str) -> str:
    table = RU_PUNCT if lang == "ru" else EN_PUNCT
    return _apply_punct(text, table)


# ─── Инициализация моделей ───────────────────────────────────────
def _model_path(*parts):
    return os.path.join(MODELS_DIR, *parts)


def create_vad():
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = _model_path("silero_vad.onnx")
    config.silero_vad.min_silence_duration = 0.25
    config.silero_vad.min_speech_duration = 0.25
    config.silero_vad.threshold = 0.5
    config.sample_rate = SAMPLE_RATE
    config.num_threads = 1
    return sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)


def create_lang_id():
    config = sherpa_onnx.SpokenLanguageIdentificationConfig(
        whisper=sherpa_onnx.SpokenLanguageIdentificationWhisperConfig(
            encoder=_model_path("sherpa-onnx-whisper-tiny", "tiny-encoder.int8.onnx"),
            decoder=_model_path("sherpa-onnx-whisper-tiny", "tiny-decoder.onnx"),
        ),
        num_threads=2,
    )
    return sherpa_onnx.SpokenLanguageIdentification(config)


def create_ru_recognizer():
    """GigaAM v2 — русский ASR через NeMo CTC"""
    return sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
        model=_model_path("gigaam-russian", "model.int8.onnx"),
        tokens=_model_path("gigaam-russian", "tokens.txt"),
        num_threads=2,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
        debug=False,
    )


def create_en_vosk():
    return VoskModel(_model_path("vosk-model-small-en-us-0.15"))


# ─── Распознавание ───────────────────────────────────────────────
def detect_language(lang_id, audio: np.ndarray) -> str:
    """Определить язык. Для очень коротких фрагментов → fallback."""
    if len(audio) < int(SAMPLE_RATE * LANG_MIN_SEC):
        return LANG_FALLBACK
    stream = lang_id.create_stream()
    stream.accept_waveform(SAMPLE_RATE, audio.tolist())
    raw = lang_id.compute(stream)
    return "ru" if raw in _SLAVIC else "en"


def recognize_russian(recognizer, audio: np.ndarray) -> str:
    stream = recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, audio.tolist())
    recognizer.decode_stream(stream)
    return stream.result.text.strip()


def recognize_english(vosk_model, audio: np.ndarray) -> str:
    rec = KaldiRecognizer(vosk_model, SAMPLE_RATE)
    rec.SetWords(False)
    int16 = (audio * 32767).astype(np.int16).tobytes()
    rec.AcceptWaveform(int16)
    result = json.loads(rec.FinalResult())
    return result.get("text", "").strip()


# ─── Основной цикл ──────────────────────────────────────────────
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

    print("⏳ Загрузка моделей...")
    vad = create_vad()
    lang_id = create_lang_id()
    ru_rec = create_ru_recognizer()
    en_model = create_en_vosk()
    print("✅ Все модели загружены. Говорите...")

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

    try:
        while True:
            data = parec.stdout.read(CHUNK_SAMPLES * 2)
            if not data:
                break

            samples = (
                np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            )
            vad.accept_waveform(samples)

            while not vad.empty():
                segment = vad.front
                audio = np.array(segment.samples, dtype=np.float32)

                # Пропускаем слишком короткие фрагменты
                if len(audio) < int(SAMPLE_RATE * MIN_SPEECH_SEC):
                    vad.pop()
                    continue

                lang = detect_language(lang_id, audio)

                # Пока всё через GigaAM — Vosk отключён
                text = recognize_russian(ru_rec, audio)
                if text:
                    text = process_text(text, lang)

                if text:
                    paste_text(text + " ")
                    print(f"  → [{lang}] {text}")

                vad.pop()

    except KeyboardInterrupt:
        pass
    finally:
        parec.terminate()
        parec.wait()
        cleanup()


if __name__ == "__main__":
    main()