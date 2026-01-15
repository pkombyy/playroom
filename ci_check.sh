#!/bin/bash
# Локальный скрипт для проверки кода (аналогично CI)

set -e

echo "🔍 Проверка синтаксиса Python..."
python -m py_compile main.py config.py
find handlers utils -name "*.py" -exec python -m py_compile {} \;
echo "✅ Синтаксис корректен"

echo "🔍 Проверка импортов..."
python -c "from handlers import rooms, tracks, rooms_create, start; from utils import youtube, google_drive, storage, redis_helper; print('✅ Все импорты успешны')"

echo "🔍 Проверка с flake8..."
if ! command -v flake8 &> /dev/null; then
    echo "⚠️  flake8 не установлен, устанавливаю..."
    pip install flake8 --quiet
fi

flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=venv,__pycache__ || true
flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics --exclude=venv,__pycache__ || true

echo "✅ Все проверки завершены"
