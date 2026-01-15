# PlayRoom

Telegram бот для создания музыкальных комнат и совместного прослушивания треков.

## Установка

1. Создайте виртуальное окружение:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Создайте файл `.env` с необходимыми переменными окружения:
```
API_TOKEN=your_telegram_bot_token
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
```

4. Запустите бота:
```bash
python main.py
```

## Зависимости

Основные пакеты:
- `aiogram==3.24.0` - Telegram Bot Framework
- `redis==7.1.0` - Redis клиент
- `yt-dlp==2025.12.8` - Загрузка аудио с YouTube
- `mutagen==1.47.0` - Работа с метаданными аудио
- `google-api-python-client==2.188.0` - Google Drive API

Полный список зависимостей см. в `requirements.txt`.

## CI/CD

Проект использует GitHub Actions для автоматической проверки кода.

### Локальная проверка

Запустите скрипт для проверки кода локально:
```bash
./ci_check.sh
```

Или вручную:
```bash
# Проверка синтаксиса
python -m py_compile main.py config.py

# Проверка импортов
python -c "from handlers import rooms, tracks, rooms_create, start; from utils import youtube, google_drive, storage, redis_helper; print('OK')"

# Линтинг
flake8 . --exclude=venv,__pycache__
```

## Асинхронная загрузка треков

Проект поддерживает параллельную загрузку треков с YouTube:

### Параллельная загрузка нескольких треков

```python
from utils.youtube import download_tracks_parallel

queries = ["Track 1", "Track 2", "Track 3"]
results = await download_tracks_parallel(queries, max_concurrent=3)
```

### Очередь загрузок

```python
from utils.youtube import get_download_queue

queue = get_download_queue()
task_id = await queue.add("Track Name", priority=1)
result = await queue.get_result(task_id)
```

### Примеры использования

См. `utils/youtube_example.py` для подробных примеров.

### Тестирование

```bash
# Тест параллельной загрузки
python test_parallel_download.py "Track 1" "Track 2" "Track 3"

# Тест одиночной загрузки
python test_youtube_download.py "Track Name"
```

## Обновление зависимостей

Для обновления пакетов до последних версий:
```bash
pip install --upgrade -r requirements.txt
```

После обновления проверьте работоспособность:
```bash
./ci_check.sh
```
