"""
Service для работы с треками
"""
from typing import Optional, Dict, Any
from repositories.track_repository import TrackRepository
from repositories.room_repository import RoomRepository
from utils.timezone import iso_now


class TrackService:
    """Сервис для работы с треками"""
    
    def __init__(self):
        self.track_repo = TrackRepository()
        self.room_repo = RoomRepository()
    
    async def add_track_to_room(
        self,
        room_id: str,
        title: str,
        file_hash: str,
        added_by: str,
        user_id: int,
        anon: bool = False
    ) -> Dict[str, Any]:
        """
        Добавляет трек в комнату
        
        Returns:
            Словарь с информацией о добавленном треке
        """
        # Проверяем на дубликаты
        existing_index = await self.track_repo.find_track_by_hash(room_id, file_hash)
        if existing_index is not None:
            raise ValueError("Трек уже существует в плейлисте")
        
        existing_index = await self.track_repo.find_track_by_title(room_id, title)
        if existing_index is not None:
            raise ValueError("Трек с таким названием уже существует")
        
        # Создаем данные трека
        track_data = {
            "title": title,
            "file": file_hash,
            "added_by": added_by,
            "user_id": user_id,
            "status": "approved"
        }
        
        # Добавляем трек
        await self.track_repo.add_track(room_id, track_data)
        
        # Сохраняем трек пользователя
        token = self._generate_token()
        user_track_data = {
            "title": title,
            "file": file_hash,
            "added_by": added_by,
            "room_id": room_id,
            "token": token,
            "status": "approved",
            "anon": anon
        }
        await self.track_repo.save_user_track(user_id, room_id, token, user_track_data)
        
        return {
            "track": track_data,
            "user_track_token": token
        }
    
    async def get_track_info(self, room_id: str, index: int) -> Optional[Dict[str, Any]]:
        """Получает информацию о треке"""
        return await self.track_repo.get_track(room_id, index)
    
    async def remove_track(self, room_id: str, index: int) -> bool:
        """Удаляет трек из комнаты"""
        return await self.track_repo.remove_track(room_id, index)
    
    async def update_track_status(
        self,
        room_id: str,
        index: int,
        status: str,
        user_id: Optional[int] = None
    ) -> bool:
        """Обновляет статус трека"""
        track = await self.track_repo.get_track(room_id, index)
        if not track:
            return False
        
        track["status"] = status
        track["moderated_at"] = iso_now()
        
        # Обновляем трек в плейлисте
        await self.track_repo.update_track(room_id, index, track)
        
        # Обновляем статус трека пользователя, если указан user_id
        if user_id:
            file_hash = track.get("file")
            user_tracks = await self.track_repo.get_user_tracks(user_id, room_id)
            for user_track in user_tracks:
                if user_track.get("file") == file_hash:
                    await self.track_repo.update_user_track_status(
                        user_id,
                        room_id,
                        user_track.get("token"),
                        status
                    )
                    break
        
        return True
    
    def _generate_token(self) -> str:
        """Генерирует токен для трека"""
        import secrets
        return secrets.token_hex(8)
