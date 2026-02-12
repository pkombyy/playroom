"""
Repository для работы с треками
"""
from typing import Optional, List, Dict, Any
from repositories.base_repository import BaseRepository
from utils.timezone import iso_now


class TrackRepository(BaseRepository):
    """Репозиторий для работы с треками"""
    
    def _track_key(self, room_id: str, index: int = None) -> str:
        """Генерирует ключ для трека"""
        if index is not None:
            return f"room:{room_id}:tracks"
        return f"room:{room_id}:tracks"
    
    def _user_track_key(self, user_id: int, room_id: str, token: str) -> str:
        """Генерирует ключ для трека пользователя"""
        return f"user_track:{user_id}:{room_id}:{token}"
    
    def _user_tracks_set_key(self, user_id: int, room_id: str) -> str:
        """Генерирует ключ для множества треков пользователя"""
        return f"user:{user_id}:tracks:{room_id}"
    
    async def get_track(self, room_id: str, index: int) -> Optional[Dict[str, Any]]:
        """Получает трек по индексу"""
        tracks = await self._list_get(self._track_key(room_id))
        if 0 <= index < len(tracks):
            return tracks[index]
        return None
    
    async def get_all_tracks(self, room_id: str) -> List[Dict[str, Any]]:
        """Получает все треки комнаты"""
        return await self._list_get(self._track_key(room_id))
    
    async def add_track(self, room_id: str, track_data: Dict[str, Any]) -> int:
        """Добавляет трек в комнату"""
        # Добавляем даты если их нет
        if "added_at" not in track_data:
            track_data["added_at"] = iso_now()
        if "moderated_at" not in track_data:
            track_data["moderated_at"] = iso_now()
        if "status" not in track_data:
            track_data["status"] = "approved"
        
        return await self._list_add(self._track_key(room_id), track_data)
    
    async def remove_track(self, room_id: str, index: int) -> bool:
        """Удаляет трек из комнаты"""
        # Помечаем как удаленный
        await self._list_set(self._track_key(room_id), index, {"__deleted__": True})
        # Удаляем из списка
        await self._list_remove(self._track_key(room_id), {"__deleted__": True})
        return True
    
    async def update_track(self, room_id: str, index: int, track_data: Dict[str, Any]) -> bool:
        """Обновляет трек"""
        return await self._list_set(self._track_key(room_id), index, track_data)
    
    async def find_track_by_hash(self, room_id: str, file_hash: str) -> Optional[int]:
        """Находит индекс трека по хешу файла"""
        tracks = await self.get_all_tracks(room_id)
        for i, track in enumerate(tracks):
            # Пропускаем удаленные треки
            if track.get("__deleted__") is True:
                continue
            if track.get("file") == file_hash:
                return i
        return None
    
    async def find_track_by_title(self, room_id: str, title: str) -> Optional[int]:
        """Находит индекс трека по названию"""
        tracks = await self.get_all_tracks(room_id)
        title_lower = title.lower()
        for i, track in enumerate(tracks):
            # Пропускаем удаленные треки
            if track.get("__deleted__") is True:
                continue
            if track.get("title", "").lower() == title_lower:
                return i
        return None
    
    async def save_user_track(self, user_id: int, room_id: str, token: str, track_data: Dict[str, Any]) -> bool:
        """Сохраняет трек пользователя"""
        if "added_at" not in track_data:
            track_data["added_at"] = iso_now()
        
        # Сохраняем трек
        key = self._user_track_key(user_id, room_id, token)
        result = await self._set(key, track_data, ex=604800)  # 7 дней
        
        # Добавляем токен в множество треков пользователя
        if result:
            await self._set_add(self._user_tracks_set_key(user_id, room_id), token)
        
        return result
    
    async def get_user_track(self, user_id: int, room_id: str, token: str) -> Optional[Dict[str, Any]]:
        """Получает трек пользователя"""
        key = self._user_track_key(user_id, room_id, token)
        return await self._get(key)
    
    async def get_user_tracks(self, user_id: int, room_id: str) -> List[Dict[str, Any]]:
        """Получает все треки пользователя в комнате"""
        tokens = await self._set_members(self._user_tracks_set_key(user_id, room_id))
        tracks = []
        for token in tokens:
            track = await self.get_user_track(user_id, room_id, token)
            if track:
                tracks.append(track)
        return tracks
    
    async def update_user_track_status(
        self, 
        user_id: int, 
        room_id: str, 
        token: str, 
        status: str,
        moderated_at: Optional[str] = None
    ) -> bool:
        """Обновляет статус трека пользователя"""
        track = await self.get_user_track(user_id, room_id, token)
        if not track:
            return False
        
        track["status"] = status
        if moderated_at:
            track["moderated_at"] = moderated_at
        elif status in ("approved", "rejected"):
            track["moderated_at"] = iso_now()
        
        return await self.save_user_track(user_id, room_id, token, track)
