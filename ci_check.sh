#!/bin/bash
# Локальный скрипт для проверки кода (аналогично CI)

set -e

echo "🚀 Запуск CI проверок..."

# Проверка синтаксиса
echo "🔍 Проверка синтаксиса Python..."
python -m py_compile main.py config.py
find handlers utils db repositories services keyboards util_types -name "*.py" -type f -exec python -m py_compile {} \;
echo "✅ Синтаксис корректен"

# Проверка импортов
echo "🔍 Проверка импортов..."
python -c "from handlers import rooms, tracks, rooms_create, start, room_management, admin, manage; from utils import youtube, google_drive, storage, redis_helper, room_permissions, timezone; from db import config; print('✅ Все импорты успешны')"

# Установка инструментов проверки
echo "🔍 Установка инструментов проверки..."
pip install --quiet flake8 black isort safety 2>/dev/null || true

# Проверка с flake8 (критические ошибки)
echo "🔍 Проверка с flake8 (критические ошибки)..."
if command -v flake8 &> /dev/null; then
    flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=venv,__pycache__,tmp,exports || exit 1
    echo "✅ Критические ошибки не найдены"
else
    echo "⚠️  flake8 не установлен, пропускаю..."
fi

# Проверка стиля (предупреждения)
echo "🔍 Проверка стиля кода..."
if command -v flake8 &> /dev/null; then
    flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics --exclude=venv,__pycache__,tmp,exports || true
fi

# Проверка форматирования
echo "🔍 Проверка форматирования кода..."
if command -v black &> /dev/null; then
    black --check --diff . --exclude='/(venv|__pycache__|tmp|exports)/' || echo "⚠️  Проблемы с форматированием (не критично)"
fi

# Проверка сортировки импортов
echo "🔍 Проверка сортировки импортов..."
if command -v isort &> /dev/null; then
    isort --check-only --diff . --skip venv --skip __pycache__ --skip tmp --skip exports || echo "⚠️  Проблемы с сортировкой импортов (не критично)"
fi

# Проверка безопасности зависимостей
echo "🔍 Проверка безопасности зависимостей..."
if command -v safety &> /dev/null; then
    safety check --file requirements.txt || echo "⚠️  Найдены уязвимости в зависимостях"
else
    echo "ℹ️  safety не установлен, пропускаю проверку безопасности"
fi

echo ""
echo "✅ Все проверки завершены!"
