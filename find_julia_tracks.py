#!/usr/bin/env python3
import asyncio
import json
import sys
sys.path.insert(0, '/var/playroom')
from config import redis
from utils.redis_helper import redis_safe

async def find():
    print("Поиск треков пользователя 'Юлия Тырина'...")
    
    keys = []
    cursor = 0
    while True:
        cursor, batch = await redis_safe(redis.scan(cursor, match='user_track:*', count=100))
        keys.extend(batch)
        if cursor == 0:
            break
    
    found = []
    for k in keys:
        key = k.decode() if isinstance(k, bytes) else str(k)
        parts = key.split(':')
        if len(parts) < 4:
            continue
        
        data = await redis_safe(redis.get(key))
        if not data:
            continue
        
        try:
            if isinstance(data, bytes):
                track = json.loads(data.decode())
            else:
                track = json.loads(data) if isinstance(data, str) else data
            
            name = track.get('added_by', '').lower()
            if 'юлия' in name and 'тырина' in name:
                room_id = parts[2]
                room_name_raw = await redis_safe(redis.get(f'room:{room_id}:name'))
                room_name = room_name_raw.decode() if isinstance(room_name_raw, bytes) else str(room_name_raw) if room_name_raw else 'Неизвестно'
                
                found.append({
                    'room': room_name,
                    'room_id': room_id,
                    'title': track.get('title', 'Неизвестно'),
                    'status': track.get('status', 'unknown'),
                    'added_by': track.get('added_by', ''),
                    'anon': track.get('anon', False)
                })
        except:
            pass
    
    if found:
        print(f"\nНайдено треков: {len(found)}\n")
        by_room = {}
        for t in found:
            rid = t['room_id']
            if rid not in by_room:
                by_room[rid] = {'name': t['room'], 'tracks': []}
            by_room[rid]['tracks'].append(t)
        
        for rid, data in by_room.items():
            print(f"Комната: {data['name']} ({rid})")
            print(f"Треков: {len(data['tracks'])}\n")
            
            for status in ['pending', 'approved', 'rejected']:
                tracks = [t for t in data['tracks'] if t['status'] == status]
                if tracks:
                    emoji = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}.get(status, '❓')
                    print(f"  {emoji} {status.upper()}: {len(tracks)}")
                    for t in tracks:
                        anon = ' (🤫 анонимно)' if t['anon'] else ''
                        print(f"    • {t['title'][:70]}{anon}")
                    print()
    else:
        print("Треки не найдены")
    
    await redis.aclose()

if __name__ == "__main__":
    asyncio.run(find())
