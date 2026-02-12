#!/usr/bin/env python3
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from config import redis
from utils.redis_helper import redis_safe

async def restore_all():
    print("🔍 Поиск всех треков со статусом pending...")
    
    # Ищем все user_track ключи
    all_keys = []
    cursor = 0
    while True:
        cursor, keys = await redis_safe(redis.scan(cursor, match="user_track:*", count=100))
        all_keys.extend(keys)
        if cursor == 0:
            break
    
    print(f"Найдено ключей: {len(all_keys)}")
    
    pending_by_room = {}
    
    # Собираем все pending треки
    for key_bytes in all_keys:
        key = key_bytes.decode() if isinstance(key_bytes, bytes) else str(key_bytes)
        parts = key.split(":")
        if len(parts) >= 4:
            user_id = parts[1]
            room_id = parts[2]
            token = parts[3]
            
            data_raw = await redis_safe(redis.get(key))
            if data_raw:
                try:
                    if isinstance(data_raw, bytes):
                        track = json.loads(data_raw.decode())
                    else:
                        track = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
                    
                    if track.get("status") == "pending":
                        if room_id not in pending_by_room:
                            pending_by_room[room_id] = []
                        pending_by_room[room_id].append({
                            "key": key,
                            "token": token,
                            "title": track.get("title", "Неизвестно"),
                            "user_id": user_id,
                            "track_data": track
                        })
                except Exception as e:
                    print(f"Ошибка при обработке {key}: {e}")
    
    print(f"\n📊 Найдено комнат с pending треками: {len(pending_by_room)}")
    
    total_restored = 0
    
    # Восстанавливаем треки по комнатам
    for room_id, tracks in pending_by_room.items():
        room_name_raw = await redis_safe(redis.get(f"room:{room_id}:name"))
        room_name = room_name_raw.decode() if isinstance(room_name_raw, bytes) else str(room_name_raw) if room_name_raw else "Неизвестно"
        
        print(f"\n🏠 Комната: {room_name} ({room_id})")
        print(f"   Найдено pending треков: {len(tracks)}")
        
        # Получаем текущую очередь
        queue_key = f"room:{room_id}:moderation_queue"
        queue_tokens_raw = await redis_safe(redis.lrange(queue_key, 0, -1))
        queue_tokens = [t.decode() if isinstance(t, bytes) else str(t) for t in (queue_tokens_raw or [])]
        
        restored = 0
        for track_info in tracks:
            token = track_info["token"]
            track_data = track_info["track_data"]
            
            # Проверяем, есть ли уже в очереди
            if token in queue_tokens:
                # Проверяем, есть ли данные
                mod_key = f"moderation_queue:{room_id}:{token}"
                mod_data = await redis_safe(redis.get(mod_key))
                if mod_data:
                    continue
            
            # Восстанавливаем
            moderation_track = {
                "title": track_data.get("title"),
                "file": track_data.get("file"),
                "added_by": track_data.get("added_by"),
                "user_id": int(track_info["user_id"]) if track_info["user_id"].isdigit() else None,
                "token": token,
                "status": "pending",
                "anon": track_data.get("anon", False),
                "added_at": track_data.get("added_at")
            }
            
            # Сохраняем данные трека
            mod_key = f"moderation_queue:{room_id}:{token}"
            await redis_safe(redis.set(mod_key, json.dumps(moderation_track), ex=86400))
            
            # Добавляем в очередь
            if token not in queue_tokens:
                await redis_safe(redis.rpush(queue_key, token))
                restored += 1
                total_restored += 1
                print(f"   ✅ Восстановлен: {track_data.get('title', 'Неизвестно')[:50]}")
        
        print(f"   📈 Восстановлено: {restored} треков")
    
    print(f"\n✅ Всего восстановлено треков: {total_restored}")
    await redis.aclose()

if __name__ == "__main__":
    asyncio.run(restore_all())
