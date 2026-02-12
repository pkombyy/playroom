#!/usr/bin/env python3
"""
Скрипт для восстановления истекших треков из pending_track
"""
import asyncio
import json
import sys
sys.path.insert(0, '/var/playroom')
from config import redis
from utils.redis_helper import redis_safe
from repositories.moderation_repository import ModerationRepository

async def restore_expired_tracks():
    """Восстанавливает все истекшие треки из user_tracks в очередь модерации"""
    print("🔍 Ищу истекшие треки для восстановления...\n")
    
    moderation_repo = ModerationRepository()
    
    # Получаем все комнаты
    room_keys = []
    cursor = 0
    while True:
        cursor, keys = await redis_safe(redis.scan(cursor, match="room:*:name", count=100))
        room_keys.extend(keys)
        if cursor == 0:
            break
    
    room_ids = []
    for k in room_keys:
        key = k.decode() if isinstance(k, bytes) else str(k)
        parts = key.split(":")
        if len(parts) >= 2:
            room_id = parts[1]
            if room_id not in room_ids:
                room_ids.append(room_id)
    
    print(f"Найдено комнат: {len(room_ids)}\n")
    
    total_restored = 0
    
    for room_id in room_ids:
        restored = await moderation_repo.restore_all_pending_from_user_tracks(room_id)
        if restored > 0:
            print(f"✅ Комната {room_id}: восстановлено {restored} треков")
            total_restored += restored
    
    print(f"\n🎉 Всего восстановлено треков: {total_restored}")
    
    # Также восстанавливаем pending_track ключи, которые могли истечь
    print("\n🔍 Проверяю pending_track ключи...")
    pending_keys = []
    cursor = 0
    while True:
        cursor, keys = await redis_safe(redis.scan(cursor, match="pending_track:*", count=100))
        pending_keys.extend(keys)
        if cursor == 0:
            break
    
    print(f"Найдено pending_track ключей: {len(pending_keys)}")
    
    # Проверяем, какие из них истекли (TTL < 0 означает, что ключ истек)
    expired_count = 0
    for k in pending_keys:
        key = k.decode() if isinstance(k, bytes) else str(k)
        ttl = await redis_safe(redis.ttl(key))
        if ttl == -1:  # Ключ существует без TTL (хорошо)
            continue
        elif ttl == -2:  # Ключ не существует (истек)
            expired_count += 1
            # Пытаемся восстановить из user_tracks
            token = key.split(":")[1] if ":" in key else None
            if token:
                # Ищем в user_tracks
                user_track_keys = []
                cursor2 = 0
                while True:
                    cursor2, keys2 = await redis_safe(redis.scan(cursor2, match=f"user_track:*:*:{token}", count=100))
                    user_track_keys.extend(keys2)
                    if cursor2 == 0:
                        break
                
                for uk in user_track_keys:
                    uk_str = uk.decode() if isinstance(uk, bytes) else str(uk)
                    parts = uk_str.split(":")
                    if len(parts) >= 4:
                        user_id = parts[1]
                        track_room_id = parts[2]
                        track_data = await redis_safe(redis.get(uk_str))
                        if track_data:
                            try:
                                if isinstance(track_data, bytes):
                                    track = json.loads(track_data.decode())
                                else:
                                    track = json.loads(track_data) if isinstance(track_data, str) else track_data
                                
                                if track.get("status") == "pending":
                                    # Восстанавливаем pending_track
                                    pending_data = {
                                        "room_id": track_room_id,
                                        "title": track.get("title"),
                                        "file": track.get("file"),
                                        "user_id": int(user_id) if user_id.isdigit() else None,
                                        "added_by": track.get("added_by", "")
                                    }
                                    await redis_safe(redis.set(key, json.dumps(pending_data)))
                                    print(f"  ✅ Восстановлен pending_track: {token} для комнаты {track_room_id}")
                                    break
                            except Exception as e:
                                print(f"  ⚠️ Ошибка при восстановлении {key}: {e}")
    
    if expired_count > 0:
        print(f"\n⚠️ Найдено истекших pending_track ключей: {expired_count}")
    else:
        print("\n✅ Все pending_track ключи в порядке")
    
    await redis.aclose()

if __name__ == "__main__":
    asyncio.run(restore_expired_tracks())
