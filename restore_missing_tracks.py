#!/usr/bin/env python3
"""Скрипт для восстановления потерянных треков на модерации"""
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from config import redis
from utils.redis_helper import redis_safe

async def restore_missing():
    print("🔍 Ищу потерянные треки...\n")
    
    # Находим все user_track ключи
    all_keys = []
    cursor = 0
    while True:
        cursor, keys = await redis_safe(redis.scan(cursor, match="user_track:*", count=100))
        all_keys.extend(keys)
        if cursor == 0:
            break
    
    print(f"Проверено ключей: {len(all_keys)}")
    
    missing = []
    
    for k in all_keys:
        key = k.decode() if isinstance(k, bytes) else str(k)
        parts = key.split(":")
        if len(parts) < 4:
            continue
        
        user_id = parts[1]
        room_id = parts[2]
        token = parts[3]
        
        data = await redis_safe(redis.get(key))
        if not data:
            continue
        
        try:
            if isinstance(data, bytes):
                track = json.loads(data.decode())
            else:
                track = json.loads(data) if isinstance(data, str) else data
            
            if track.get("status") == "pending":
                # Проверяем очередь модерации
                queue_key = f"room:{room_id}:moderation_queue"
                queue_raw = await redis_safe(redis.lrange(queue_key, 0, -1))
                queue_tokens = [t.decode() if isinstance(t, bytes) else str(t) for t in (queue_raw or [])]
                
                # Проверяем данные трека
                mod_key = f"moderation_queue:{room_id}:{token}"
                mod_data = await redis_safe(redis.get(mod_key))
                
                # Если нет ни в очереди, ни в данных - трек потерян
                if token not in queue_tokens and not mod_data:
                    room_name_raw = await redis_safe(redis.get(f"room:{room_id}:name"))
                    room_name = room_name_raw.decode() if isinstance(room_name_raw, bytes) else str(room_name_raw) if room_name_raw else "Неизвестно"
                    
                    missing.append({
                        "room_id": room_id,
                        "room_name": room_name,
                        "token": token,
                        "user_id": user_id,
                        "title": track.get("title", "Неизвестно"),
                        "track": track
                    })
        except:
            pass
    
    print(f"\n📊 Найдено потерянных треков: {len(missing)}\n")
    
    if missing:
        for i, m in enumerate(missing, 1):
            print(f"{i}. {m['title'][:60]}")
            print(f"   Комната: {m['room_name']} ({m['room_id']})")
            print(f"   Пользователь: {m['user_id']}")
            print(f"   Token: {m['token']}\n")
        
        print("🔄 Восстанавливаю...\n")
        
        for m in missing:
            mod_track = {
                "title": m["track"].get("title"),
                "file": m["track"].get("file"),
                "added_by": m["track"].get("added_by"),
                "user_id": int(m["user_id"]) if m["user_id"].isdigit() else None,
                "token": m["token"],
                "status": "pending",
                "anon": m["track"].get("anon", False),
                "added_at": m["track"].get("added_at")
            }
            
            # Сохраняем данные
            mod_key = f"moderation_queue:{m['room_id']}:{m['token']}"
            await redis_safe(redis.set(mod_key, json.dumps(mod_track), ex=86400))
            
            # Добавляем в очередь
            queue_key = f"room:{m['room_id']}:moderation_queue"
            await redis_safe(redis.rpush(queue_key, m["token"]))
            
            print(f"✅ Восстановлен: {m['title'][:50]}")
        
        print(f"\n✅ Всего восстановлено: {len(missing)} треков")
    else:
        print("✅ Потерянных треков не найдено - все в порядке!")
    
    await redis.aclose()

if __name__ == "__main__":
    asyncio.run(restore_missing())
