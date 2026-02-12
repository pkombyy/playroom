#!/usr/bin/env python3
"""
Скрипт для восстановления всех треков со статусом pending в очередь модерации
"""
import asyncio
import json
import sys
from pathlib import Path

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from config import redis
from utils.redis_helper import redis_safe
from repositories.moderation_repository import ModerationRepository

async def restore_all_pending_tracks():
    """Восстанавливает все треки со статусом pending в очередь модерации"""
    moderation_repo = ModerationRepository()
    
    # Ищем все user_track ключи
    pattern = "user_track:*:*:*"
    all_keys = await redis_safe(redis.keys(pattern))
    
    if not all_keys:
        print("Треки не найдены")
        return
    
    print(f"Найдено ключей user_track: {len(all_keys)}")
    
    restored_count = 0
    already_in_queue = 0
    rooms_stats = {}
    
    for key_bytes in all_keys:
        key = key_bytes.decode() if isinstance(key_bytes, bytes) else str(key_bytes)
        parts = key.split(":")
        
        if len(parts) < 4:
            continue
            
        user_id = parts[1]
        room_id = parts[2]
        token = parts[3]
        
        # Получаем трек
        track_data = await moderation_repo._get(key)
        if not track_data:
            continue
        
        # Проверяем статус
        status = track_data.get("status", "approved")
        if status != "pending":
            continue
        
        # Инициализируем статистику для комнаты
        if room_id not in rooms_stats:
            rooms_stats[room_id] = {"restored": 0, "already": 0}
        
        # Проверяем, есть ли уже в очереди модерации
        queue_key = f"room:{room_id}:moderation_queue"
        queue_tokens_raw = await redis_safe(redis.lrange(queue_key, 0, -1))
        queue_tokens = [t.decode() if isinstance(t, bytes) else str(t) for t in (queue_tokens_raw or [])]
        
        if token in queue_tokens:
            # Проверяем, есть ли данные трека в moderation_queue
            mod_key = f"moderation_queue:{room_id}:{token}"
            mod_track = await moderation_repo._get(mod_key)
            if mod_track:
                already_in_queue += 1
                rooms_stats[room_id]["already"] += 1
                continue
        
        # Восстанавливаем трек
        moderation_track = {
            "title": track_data.get("title"),
            "file": track_data.get("file"),
            "added_by": track_data.get("added_by"),
            "user_id": int(user_id) if user_id.isdigit() else None,
            "token": token,
            "status": "pending",
            "anon": track_data.get("anon", False),
            "added_at": track_data.get("added_at")
        }
        
        # Сохраняем в очередь модерации
        mod_key = f"moderation_queue:{room_id}:{token}"
        await moderation_repo._set(mod_key, moderation_track, ex=86400)
        
        # Добавляем в очередь, если еще нет
        if token not in queue_tokens:
            await redis_safe(redis.rpush(queue_key, token))
        
        restored_count += 1
        rooms_stats[room_id]["restored"] += 1
        
        print(f"✅ Восстановлен: {track_data.get('title', 'Неизвестно')[:50]} (комната: {room_id})")
    
    print(f"\n📊 Статистика восстановления:")
    print(f"  Восстановлено треков: {restored_count}")
    print(f"  Уже в очереди: {already_in_queue}")
    print(f"\nПо комнатам:")
    for room_id, stats in rooms_stats.items():
        room_name_raw = await redis_safe(redis.get(f"room:{room_id}:name"))
        room_name = room_name_raw.decode() if isinstance(room_name_raw, bytes) else str(room_name_raw) if room_name_raw else "Неизвестно"
        print(f"  {room_name} ({room_id}):")
        print(f"    Восстановлено: {stats['restored']}")
        print(f"    Уже было: {stats['already']}")
    
    await redis.aclose()

if __name__ == "__main__":
    asyncio.run(restore_all_pending_tracks())
