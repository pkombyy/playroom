#!/bin/bash
# Установка Deno для yt-dlp (требуется для YouTube с 2025)
set -e

# unzip нужен для распаковки Deno
if ! command -v unzip &>/dev/null; then
    echo "📦 Установка unzip..."
    apt-get update -qq && apt-get install -y unzip
fi

DENO_DIR="${DENO_INSTALL:-/opt/deno}"
DENO_BIN="$DENO_DIR/bin/deno"

if command -v deno &>/dev/null; then
    echo "✅ Deno уже установлен: $(deno --version)"
    exit 0
fi

echo "📥 Установка Deno..."
curl -fsSL https://deno.land/install.sh | DENO_INSTALL=$DENO_DIR sh

if [ -f "$DENO_BIN" ]; then
    # Создаём symlink для глобального доступа
    ln -sf "$DENO_BIN" /usr/local/bin/deno 2>/dev/null || true
    echo "✅ Deno установлен: $($DENO_BIN --version)"
    echo "   Путь: $DENO_BIN"
else
    echo "❌ Ошибка установки Deno"
    exit 1
fi
