#!/usr/bin/env python3
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from config import redis
from utils.redis_helper import redis_safe

async def find_tracks():
    print("🔍 Ищу треки пользователя 'Юлия Тырина'...\n")
    
    all_keys = []
    cursor = 0
    while True:
        cursor, keys = await redis_safe(redis.scan(cursor, match="user_track:*", count=100))
        all_keys.extend(keys)
        if cursor == 0:
            break
    
    print(f"Проверяю {len(all_keys)} ключей...\n")
    
    user_tracks = []
    
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
            
            added_by = track.get("added_by", "").lower()
            if "юлия" in added_by and "тырина" in added_by:
                room_name_raw = await redis_safe(redis.get(f"room:{room_id}:name"))
                room_name = room_name_raw.decode() if isinstance(room_name_raw, bytes) else str(room_name_raw) if room_name_raw else "Неизвестно"
                
                user_tracks.append({
                    "user_id": user_id,
                    "room_id": room_id,
                    "room_name": room_name,
                    "token": token,
                    "title": track.get("title", "Неизвестно"),
                    "status": track.get("status", "unknown"),
                    "added_by": track.get("added_by", ""),
                    "added_at": track.get("added_at", ""),
                    "anon": track.get("anon", False)
                })
        except:
            pass
    
    if user_tracks:
        print(f"📊 Найдено треков: {len(user_tracks)}\n")
        
        by_room = {}
        for track in user_tracks:
            room_id = track["room_id"]
            if room_id not in by_room:
                by_room[room_id] = {"name": track["room_name"], "tracks": []}
            by_room[room_id]["tracks"].append(track)
        
        for room_id, data in by_room.items():
            print(f"🏠 {data['name']} ({room_id})")
            print(f"   Треков: {len(data['tracks'])}\n")
            
            by_status = {}
            for track in data["tracks"]:
                status = track["status"]
                if status not in by_status:
                    by_status[status] = []
                by_status[status].append(track)
            
            for status in ["pending", "approved", "rejected"]:
                if status in by_status:
                    emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(status, "❓")
                    tracks = by_status[status]
                    print(f"   {emoji} {status.upper()}: {len(tracks)}")
                    for track in tracks:
                        anon = " (🤫 анонимно)" if track["anon"] else ""
                        print(f"      • {track['title'][:60]}{anon}")
                    print()
    else:
        print("❌ Треки не найдены")
        print("\nИщу похожие имена...")
        
        similar = set()
        for k in all_keys[:200]:
            key = k.decode() if isinstance(k, bytes) else str(k)
            data = await redis_safe(redis.get(key))
            if data:
                try:
                    if isinstance(data, bytes):
                        track = json.loads(data.decode())
                    else:
                        track = json.loads(data) if isinstance(data, str) else data
                    added_by = track.get("added_by", "").lower()
                    if "юлия" in added_by or "тырина" in added_by:
                        similar.add(track.get("added_by", ""))
                except:
                    pass
        
        if similar:
            print("Найдены похожие имена:")
            for name in list(similar)[:10]:
                print(f"  • {name}")
    
    await redis.aclose()

if __name__ == "__main__":
    asyncio.run(find_tracks())
