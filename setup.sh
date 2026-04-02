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

# ─── Системные зависимости ──────────────────────────────────────
for cmd in parec xclip xdotool python3 git; do
    command -v "$cmd" &>/dev/null || error "'$cmd' не найден."
done

# libc++ нужен для libsoda.so
if command -v pacman &>/dev/null; then
    pacman -Qi libc++ &>/dev/null 2>&1 \
        || warn "Установите libc++:  sudo pacman -S libc++"
    pacman -Qi alsa-utils &>/dev/null 2>&1 \
        || warn "Рекомендуется alsa-utils:  sudo pacman -S alsa-utils"
fi

# ─── Клонирование gasr ──────────────────────────────────────────
if [ ! -d "$PROJECT_DIR/gasr" ]; then
    info "Клонирую gasr..."
    git clone https://github.com/biemster/gasr.git "$PROJECT_DIR/gasr"
else
    info "gasr/ уже есть"
fi

cd "$PROJECT_DIR/gasr"

# ─── Скачивание SODA и моделей ──────────────────────────────────
info "Скачиваю libsoda..."
python3 prep.py -s

info "Скачиваю русскую модель (ru-ru)..."
python3 prep.py -s -l "ru-ru"

info "Скачиваю английскую модель (en-us)..."
python3 prep.py -s -l "en-us"

info "Скачиваю доп. пакет (zork)..."
python3 prep.py -s -p zork

# ─── Проверка ────────────────────────────────────────────────────
cd "$PROJECT_DIR"

if [ -f "$PROJECT_DIR/gasr/libsoda.so" ] && [ -d "$PROJECT_DIR/gasr/SODAModels" ]; then
    echo ""
    info "Установка завершена!"
    echo ""
    echo "    gasr/libsoda.so"
    echo "    gasr/SODAModels/"
    echo ""
    info "Запуск:  ./dictation-toggle.sh"
    echo ""

    # Подсказка по очистке старых файлов
    OLD_DIRS=()
    [ -d "$PROJECT_DIR/models" ] && OLD_DIRS+=("models/")
    [ -d "$PROJECT_DIR/lib" ]    && OLD_DIRS+=("lib/")
    [ -d "$PROJECT_DIR/.venv" ]  && OLD_DIRS+=(".venv/")
    if [ ${#OLD_DIRS[@]} -gt 0 ]; then
        warn "Старые файлы можно удалить:  rm -rf ${OLD_DIRS[*]}"
    fi
else
    error "Что-то пошло не так — проверьте вывод выше."
fi