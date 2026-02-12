#!/usr/bin/env python3
"""
Удаляет треки, превышающие лимит Telegram (50 МБ).
Удаляет файлы из кэша и убирает ссылки на них из комнат.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import redis
from utils.redis_helper import redis_safe
from utils.youtube import CACHE_DIR

# Лимит Telegram для документов/аудио: 50 МБ
TG_MAX_SIZE_BYTES = 50 * 1024 * 1024


async def main():
    """Находит и удаляет переразмеренные треки."""
    # 1. Найти все .mp3 в кэше размером > 50 МБ
    oversized = []
    for p in CACHE_DIR.glob("*.mp3"):
        try:
            size = p.stat().st_size
            if size > TG_MAX_SIZE_BYTES:
                file_hash = p.stem
                oversized.append((file_hash, size, p))
        except OSError:
            pass

    if not oversized:
        print("✅ Переразмеренных треков не найдено.")
        return

    print(f"📋 Найдено {len(oversized)} треков > 50 МБ:")
    for h, s, _ in oversized:
        print(f"   {h}: {s / (1024*1024):.1f} МБ")

    # 2. Получить все room:*:tracks ключи
    room_track_keys = []
    cursor = 0
    while True:
        cursor, keys = await redis_safe(redis.scan(cursor, match="room:*:tracks", count=100))
        for k in keys:
            key = k.decode() if isinstance(k, bytes) else str(k)
            if key not in room_track_keys:
                room_track_keys.append(key)
        if cursor == 0:
            break

    removed_from_rooms = 0
    for file_hash, size, cache_path in oversized:
        for key in room_track_keys:
            parts = key.split(":")
            if len(parts) < 2:
                continue
            room_id = parts[1]

            tracks_raw = await redis_safe(redis.lrange(key, 0, -1)) or []
            to_remove = []
            for i, item_raw in enumerate(tracks_raw):
                if item_raw == "__deleted__":
                    continue
                try:
                    if isinstance(item_raw, bytes):
                        item_raw = item_raw.decode()
                    track = json.loads(item_raw)
                    if track.get("file") == file_hash:
                        to_remove.append((i, item_raw, track.get("title", file_hash)[:50]))
                except Exception:
                    pass

            # Удаляем с конца, чтобы индексы не сдвигались
            for i, item_raw, title in sorted(to_remove, key=lambda x: -x[0]):
                await redis_safe(redis.lset(key, i, "__deleted__"))
                await redis_safe(redis.lrem(key, 1, "__deleted__"))
                removed_from_rooms += 1
                print(f"   Удалён из room:{room_id}: {title}")

    # 3. Удалить файлы из кэша
    deleted_files = 0
    for file_hash, _, cache_path in oversized:
        try:
            cache_path.unlink()
            deleted_files += 1
            meta = CACHE_DIR / f"{file_hash}.json"
            if meta.exists():
                meta.unlink()
        except OSError as e:
            print(f"   ⚠️ Не удалось удалить {cache_path}: {e}")

    print(f"\n✅ Готово: удалено {deleted_files} файлов, {removed_from_rooms} ссылок из комнат.")


if __name__ == "__main__":
    asyncio.run(main())
