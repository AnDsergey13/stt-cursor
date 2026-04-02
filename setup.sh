#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# ─── Проверяем системные зависимости ──────────────────────────
for cmd in parec xclip xdotool wget unzip python3; do
    command -v "$cmd" &>/dev/null || error "'$cmd' не найден. Установите: sudo pacman -S pulseaudio xclip xdotool wget unzip python"
done

command -v uv &>/dev/null || error "'uv' не найден. Установите: curl -LsSf https://astral.sh/uv/install.sh | sh"

# ─── Python-зависимости ──────────────────────────────────────
info "Устанавливаю Python-зависимости..."
uv add sherpa-onnx vosk numpy 2>/dev/null || true

# ─── Нативный onnxruntime для sherpa-onnx ─────────────────────
ONNX_VERSION="1.23.2"
if [ ! -f "lib/libonnxruntime.so.${ONNX_VERSION}" ]; then
    info "Скачиваю onnxruntime ${ONNX_VERSION}..."
    mkdir -p lib
    wget -q --show-progress \
        "https://github.com/microsoft/onnxruntime/releases/download/v${ONNX_VERSION}/onnxruntime-linux-x64-${ONNX_VERSION}.tgz" \
        -O "/tmp/onnxruntime-${ONNX_VERSION}.tgz"
    tar xzf "/tmp/onnxruntime-${ONNX_VERSION}.tgz" \
        "onnxruntime-linux-x64-${ONNX_VERSION}/lib/libonnxruntime.so.${ONNX_VERSION}"
    mv "onnxruntime-linux-x64-${ONNX_VERSION}/lib/libonnxruntime.so.${ONNX_VERSION}" lib/
    ln -sf "libonnxruntime.so.${ONNX_VERSION}" lib/libonnxruntime.so
    rm -rf "onnxruntime-linux-x64-${ONNX_VERSION}" "/tmp/onnxruntime-${ONNX_VERSION}.tgz"
    info "onnxruntime → lib/"
else
    info "onnxruntime уже есть в lib/"
fi

# ─── Модели ────────────────────────────────────────────────────
MODELS_DIR="$PROJECT_DIR/models"
mkdir -p "$MODELS_DIR"

# Silero VAD
if [ ! -f "$MODELS_DIR/silero_vad.onnx" ]; then
    info "Скачиваю Silero VAD..."
    wget -q --show-progress -O "$MODELS_DIR/silero_vad.onnx" \
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
fi

# Whisper tiny (для определения языка)
if [ ! -d "$MODELS_DIR/sherpa-onnx-whisper-tiny" ]; then
    info "Скачиваю Whisper tiny (язык-детектор)..."
    wget -q --show-progress \
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-tiny.tar.bz2" \
        -O "/tmp/whisper-tiny.tar.bz2"
    tar xjf "/tmp/whisper-tiny.tar.bz2" -C "$MODELS_DIR"
    rm -f "/tmp/whisper-tiny.tar.bz2"
fi

# GigaAM Russian
if [ ! -f "$MODELS_DIR/gigaam-russian/model.int8.onnx" ]; then
    info "Скачиваю GigaAM v2 (русский ASR)..."
    wget -q --show-progress \
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-ctc-giga-am-v2-russian-2025-04-19.tar.bz2" \
        -O "/tmp/gigaam.tar.bz2"
    tar xjf "/tmp/gigaam.tar.bz2" -C "/tmp"
    mv "/tmp/sherpa-onnx-nemo-ctc-giga-am-v2-russian-2025-04-19" "$MODELS_DIR/gigaam-russian"
    rm -f "/tmp/gigaam.tar.bz2"
fi

# Vosk English small
if [ ! -d "$MODELS_DIR/vosk-model-small-en-us-0.15" ]; then
    info "Скачиваю Vosk English small..."
    wget -q --show-progress \
        "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" \
        -O "/tmp/vosk-en.zip"
    unzip -q "/tmp/vosk-en.zip" -d "$MODELS_DIR"
    rm -f "/tmp/vosk-en.zip"
fi

# ─── Готово ────────────────────────────────────────────────────
info "Все модели загружены:"
echo "    models/silero_vad.onnx"
echo "    models/sherpa-onnx-whisper-tiny/"
echo "    models/gigaam-russian/"
echo "    models/vosk-model-small-en-us-0.15/"
echo ""
info "Запуск: ./dictation-toggle.sh"
info "Или вручную: LD_LIBRARY_PATH=$(pwd)/lib:\$LD_LIBRARY_PATH uv run python main.py"