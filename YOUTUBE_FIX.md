# Исправление загрузки с YouTube

## Проблема
- `HTTP Error 403: Forbidden` при загрузке
- `No supported JavaScript runtime could be found`
- `YouTube is forcing SABR streaming`

## Решение (применено)

### 1. Установлен Deno (JS runtime)
```bash
sudo /var/playroom/scripts/install_deno.sh
```
Deno требуется yt-dlp для обхода ограничений YouTube.

### 2. Обновлён yt-dlp с EJS
```bash
pip install -U "yt-dlp[default]"
```
Пакет `yt-dlp[default]` включает `yt-dlp-ejs` — скрипты для обхода блокировок.

### 3. Изменения в utils/youtube.py
Добавлен `extractor_args` с android-клиентом — часто обходит 403.

## Перезапуск бота

После изменений:
```bash
./start_bot.sh
# или
systemctl restart your-bot-service
```

## Проверка

```bash
cd /var/playroom
source venv/bin/activate
python3 -c "
import asyncio
from utils.youtube import download_track
r = asyncio.run(download_track('https://www.youtube.com/watch?v=dQw4w9WgXcQ'))
print('OK' if r else 'FAIL')
"
```
