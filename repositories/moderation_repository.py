"""
Repository для работы с модерацией
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from repositories.base_repository import BaseRepository
from utils.timezone import iso_now, now_tyumen, parse_iso
from utils.redis_helper import redis_safe


class ModerationRepository(BaseRepository):
    """Репозиторий для работы с модерацией"""
    
    def _moderation_queue_key(self, room_id: str) -> str:
        return f"room:{room_id}:moderation_queue"
    
    def _moderation_track_key(self, room_id: str, token: str) -> str:
        return f"moderation_queue:{room_id}:{token}"
    
    def _rejected_tracks_key(self, room_id: str) -> str:
        return f"room:{room_id}:rejected_tracks"
    
    def _rejected_track_key(self, room_id: str, token: str) -> str:
        return f"rejected_tracks:{room_id}:{token}"
    
    async def add_to_moderation_queue(self, room_id: str, token: str, track_data: Dict[str, Any]) -> bool:
        """Добавляет трек в очередь модерации"""
        if "status" not in track_data:
            track_data["status"] = "pending"
        if "added_at" not in track_data:
            track_data["added_at"] = iso_now()
        
        # Сохраняем трек
        key = self._moderation_track_key(room_id, token)
        result = await self._set(key, track_data, ex=86400)  # 24 часа
        
        # Добавляем в очередь
        if result:
            await redis_safe(self.redis.rpush(self._moderation_queue_key(room_id), token))
        
        return result
    
    async def get_moderation_track(self, room_id: str, token: str) -> Optional[Dict[str, Any]]:
        """Получает трек из очереди модерации"""
        key = self._moderation_track_key(room_id, token)
        return await self._get(key)
    
    async def get_pending_tracks(self, room_id: str) -> List[Dict[str, Any]]:
        """Получает список треков со статусом pending"""
        queue_tokens = await redis_safe(self.redis.lrange(self._moderation_queue_key(room_id), 0, -1))
        tokens = [
            t.decode() if isinstance(t, bytes) else str(t)
            for t in (queue_tokens or [])
        ]
        
        now = now_tyumen()
        pending_tracks = []
        found_tokens = set()
        
        # Обрабатываем треки из очереди
        for token in tokens:
            track = await self.get_moderation_track(room_id, token)
            if not track:
                continue
            
            status = track.get("status", "pending")
            
            # Если трек в обработке, проверяем время (5 минут)
            if status == "in_progress":
                moderated_at_str = track.get("moderated_at")
                if moderated_at_str:
                    try:
                        moderated_at = parse_iso(moderated_at_str)
                        if (now - moderated_at).total_seconds() > 300:
                            # Возвращаем в pending
                            track["status"] = "pending"
                            track["moderated_by"] = None
                            track["moderated_at"] = None
                            await self._set(self._moderation_track_key(room_id, token), track, ex=86400)
                            status = "pending"
                    except Exception:
                        track["status"] = "pending"
                        track["moderated_by"] = None
                        track["moderated_at"] = None
                        await self._set(self._moderation_track_key(room_id, token), track, ex=86400)
                        status = "pending"
            
            if status == "pending":
                track["token"] = token
                pending_tracks.append(track)
                found_tokens.add(token)
        
        # Восстанавливаем треки из user_tracks, которые не в очереди
        # Ищем все user_track ключи для этой комнаты
        pattern = f"user_track:*:{room_id}:*"
        try:
            # Используем SCAN вместо KEYS для больших баз данных
            all_keys = []
            cursor = 0
            while True:
                cursor, keys = await redis_safe(self.redis.scan(cursor, match=pattern, count=100))
                all_keys.extend(keys)
                if cursor == 0:
                    break
            
            restored_count = 0
            
            for key_bytes in all_keys:
                key = key_bytes.decode() if isinstance(key_bytes, bytes) else str(key_bytes)
                parts = key.split(":")
                if len(parts) >= 4:
                    user_id = parts[1]
                    token = parts[3]
                    
                    # Пропускаем, если уже в очереди
                    if token in found_tokens:
                        continue
                    
                    # Получаем трек пользователя
                    track_data = await self._get(key)
                    if not track_data:
                        continue
                    
                    # Проверяем статус
                    status = track_data.get("status", "approved")
                    if status == "pending":
                        # Восстанавливаем в очередь модерации
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
                        mod_key = self._moderation_track_key(room_id, token)
                        await self._set(mod_key, moderation_track, ex=86400)
                        
                        # Добавляем в очередь, если еще нет
                        queue_key = self._moderation_queue_key(room_id)
                        existing_tokens = await redis_safe(self.redis.lrange(queue_key, 0, -1))
                        existing = [t.decode() if isinstance(t, bytes) else str(t) for t in (existing_tokens or [])]
                        if token not in existing:
                            await redis_safe(self.redis.rpush(queue_key, token))
                        
                        moderation_track["token"] = token
                        pending_tracks.append(moderation_track)
                        found_tokens.add(token)
                        restored_count += 1
            
            if restored_count > 0:
                print(f"✅ Восстановлено {restored_count} треков в очередь модерации для комнаты {room_id}")
        except Exception as e:
            print(f"⚠️ Ошибка при восстановлении треков из user_tracks: {e}")
            import traceback
            traceback.print_exc()
        
        # Сортируем по дате добавления (старые первыми)
        pending_tracks.sort(key=lambda x: x.get("added_at", ""))
        
        return pending_tracks
    
    async def set_track_in_progress(self, room_id: str, token: str, admin_id: int) -> bool:
        """Устанавливает статус трека как 'в обработке'"""
        track = await self.get_moderation_track(room_id, token)
        if not track:
            return False
        
        track["status"] = "in_progress"
        track["moderated_by"] = admin_id
        track["moderated_at"] = iso_now()
        
        key = self._moderation_track_key(room_id, token)
        return await self._set(key, track, ex=86400)
    
    async def remove_from_moderation_queue(self, room_id: str, token: str) -> bool:
        """Удаляет трек из очереди модерации"""
        # Удаляем из списка
        await redis_safe(self.redis.lrem(self._moderation_queue_key(room_id), 1, token))
        # Удаляем данные
        key = self._moderation_track_key(room_id, token)
        return await self._delete(key)
    
    async def add_to_rejected(self, room_id: str, token: str, track_data: Dict[str, Any]) -> bool:
        """Добавляет трек в список отклоненных"""
        track_data["moderated_at"] = iso_now()
        key = self._rejected_track_key(room_id, token)
        result = await self._set(key, track_data, ex=2592000)  # 30 дней
        
        if result:
            await redis_safe(self.redis.rpush(self._rejected_tracks_key(room_id), token))
        
        return result
    
    async def get_rejected_track(self, room_id: str, token: str) -> Optional[Dict[str, Any]]:
        """Получает отклоненный трек"""
        key = self._rejected_track_key(room_id, token)
        return await self._get(key)
    
    async def get_rejected_tracks(self, room_id: str) -> List[Dict[str, Any]]:
        """Получает все отклоненные треки"""
        tokens_raw = await redis_safe(self.redis.lrange(self._rejected_tracks_key(room_id), 0, -1))
        tokens = [
            t.decode() if isinstance(t, bytes) else str(t)
            for t in (tokens_raw or [])
        ]
        
        tracks = []
        for token in tokens:
            track = await self.get_rejected_track(room_id, token)
            if track:
                track["token"] = token
                tracks.append(track)
        
        return tracks
    
    async def remove_from_rejected(self, room_id: str, token: str) -> bool:
        """Удаляет трек из списка отклоненных"""
        await redis_safe(self.redis.lrem(self._rejected_tracks_key(room_id), 1, token))
        key = self._rejected_track_key(room_id, token)
        return await self._delete(key)
    
    async def restore_all_pending_from_user_tracks(self, room_id: str = None) -> int:
        """
        Восстанавливает все треки со статусом pending из user_tracks в очередь модерации.
        Если room_id не указан, проверяет все комнаты.
        
        Returns:
            Количество восстановленных треков
        """
        import json
        
        restored_count = 0
        
        # Определяем паттерн поиска
        if room_id:
            pattern = f"user_track:*:{room_id}:*"
        else:
            pattern = "user_track:*"
        
        # Ищем все ключи
        all_keys = []
        cursor = 0
        while True:
            cursor, keys = await redis_safe(self.redis.scan(cursor, match=pattern, count=100))
            all_keys.extend(keys)
            if cursor == 0:
                break
        
        for key_bytes in all_keys:
            key = key_bytes.decode() if isinstance(key_bytes, bytes) else str(key_bytes)
            parts = key.split(":")
            if len(parts) < 4:
                continue
            
            user_id = parts[1]
            track_room_id = parts[2]
            token = parts[3]
            
            # Если указана комната, проверяем совпадение
            if room_id and track_room_id != room_id:
                continue
            
            # Получаем трек
            track_data = await self._get(key)
            if not track_data:
                continue
            
            # Проверяем статус
            if track_data.get("status") != "pending":
                continue
            
            # Проверяем, есть ли уже в очереди
            queue_key = self._moderation_queue_key(track_room_id)
            queue_tokens_raw = await redis_safe(self.redis.lrange(queue_key, 0, -1))
            queue_tokens = [t.decode() if isinstance(t, bytes) else str(t) for t in (queue_tokens_raw or [])]
            
            if token in queue_tokens:
                # Проверяем данные
                mod_key = self._moderation_track_key(track_room_id, token)
                mod_data = await self._get(mod_key)
                if mod_data:
                    continue
            
            # Восстанавливаем трек
            moderation_track = {
                "title": track_data.get("title"),
                "file": track_data.get("file"),
                "added_by": track_data.get("added_by"),
                "user_id": int(user_id) if user_id.isdigit() else track_data.get("user_id"),
                "token": token,
                "status": "pending",
                "anon": track_data.get("anon", False),
                "added_at": track_data.get("added_at")
            }
            
            # Сохраняем данные
            mod_key = self._moderation_track_key(track_room_id, token)
            await self._set(mod_key, moderation_track, ex=86400)
            
            # Добавляем в очередь
            if token not in queue_tokens:
                await redis_safe(self.redis.rpush(queue_key, token))
            
            restored_count += 1
        
        return restored_count