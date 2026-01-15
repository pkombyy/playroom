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
