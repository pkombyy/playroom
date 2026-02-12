"""
Service для работы с модерацией
"""
from typing import Optional, List, Dict, Any
from repositories.moderation_repository import ModerationRepository
from repositories.track_repository import TrackRepository
from repositories.room_repository import RoomRepository
from utils.timezone import iso_now


class ModerationService:
    """Сервис для работы с модерацией"""
    
    def __init__(self):
        self.moderation_repo = ModerationRepository()
        self.track_repo = TrackRepository()
        self.room_repo = RoomRepository()
    
    async def submit_for_moderation(
        self,
        room_id: str,
        title: str,
        file_hash: str,
        added_by: str,
        user_id: int,
        anon: bool = False
    ) -> str:
        """
        Отправляет трек на модерацию
        
        Returns:
            Токен трека в модерации
        """
        token = self._generate_token()
        
        track_data = {
            "title": title,
            "file": file_hash,
            "added_by": added_by,
            "user_id": user_id,
            "token": token,
            "anon": anon
        }
        
        await self.moderation_repo.add_to_moderation_queue(room_id, token, track_data)
        
        # Сохраняем трек пользователя со статусом pending
        user_track_data = {
            "title": title,
            "file": file_hash,
            "added_by": added_by,
            "room_id": room_id,
            "token": token,
            "status": "pending",
            "anon": anon
        }
        await self.track_repo.save_user_track(user_id, room_id, token, user_track_data)
        
        return token
    
    async def get_pending_tracks(self, room_id: str) -> List[Dict[str, Any]]:
        """Получает список треков на модерации"""
        return await self.moderation_repo.get_pending_tracks(room_id)
    
    async def approve_track(
        self,
        room_id: str,
        token: str,
        admin_id: int
    ) -> Dict[str, Any]:
        """
        Одобряет трек
        
        Returns:
            Информация об одобренном треке
        """
        # Получаем трек из модерации
        track_data = await self.moderation_repo.get_moderation_track(room_id, token)
        if not track_data:
            raise ValueError("Трек не найден в очереди модерации")
        
        # Проверяем на дубликаты
        file_hash = track_data.get("file")
        existing_index = await self.track_repo.find_track_by_hash(room_id, file_hash)
        if existing_index is not None:
            # Трек уже существует в плейлисте - просто удаляем из модерации и обновляем статус
            await self.moderation_repo.remove_from_moderation_queue(room_id, token)
            
            # Обновляем статус трека пользователя на approved (если он был pending)
            user_id = track_data.get("user_id")
            if user_id:
                # Находим все user_tracks с этим хешем и обновляем их статус
                user_tracks = await self.track_repo.get_user_tracks(user_id, room_id)
                for user_track in user_tracks:
                    if user_track.get("file") == file_hash and user_track.get("status") == "pending":
                        await self.track_repo.update_user_track_status(
                            user_id, room_id, user_track.get("token"), "approved"
                        )
            
            # Возвращаем информацию о существующем треке
            tracks = await self.track_repo.get_all_tracks(room_id)
            existing_track = tracks[existing_index] if existing_index < len(tracks) else None
            
            return {
                "track": existing_track or track_data,
                "user_id": user_id,
                "already_exists": True
            }
        
        # Устанавливаем статус in_progress
        await self.moderation_repo.set_track_in_progress(room_id, token, admin_id)
        
        # Добавляем трек в плейлист
        track_obj = {
            "title": track_data.get("title"),
            "file": file_hash,
            "added_by": track_data.get("added_by"),
            "user_id": track_data.get("user_id"),
            "status": "approved"
        }
        await self.track_repo.add_track(room_id, track_obj)
        
        # Удаляем из очереди модерации
        await self.moderation_repo.remove_from_moderation_queue(room_id, token)
        
        # Обновляем статус трека пользователя
        user_id = track_data.get("user_id")
        if user_id:
            await self.track_repo.update_user_track_status(user_id, room_id, token, "approved")
        
        return {
            "track": track_obj,
            "user_id": user_id
        }
    
    async def reject_track(
        self,
        room_id: str,
        token: str,
        admin_id: int
    ) -> Dict[str, Any]:
        """
        Отклоняет трек
        
        Returns:
            Информация об отклоненном треке
        """
        # Получаем трек из модерации
        track_data = await self.moderation_repo.get_moderation_track(room_id, token)
        if not track_data:
            raise ValueError("Трек не найден в очереди модерации")
        
        # Устанавливаем статус in_progress
        await self.moderation_repo.set_track_in_progress(room_id, token, admin_id)
        
        # Добавляем в список отклоненных
        await self.moderation_repo.add_to_rejected(room_id, token, track_data)
        
        # Удаляем из очереди модерации
        await self.moderation_repo.remove_from_moderation_queue(room_id, token)
        
        # Обновляем статус трека пользователя
        user_id = track_data.get("user_id")
        if user_id:
            await self.track_repo.update_user_track_status(user_id, room_id, token, "rejected")
        
        return {
            "track": track_data,
            "user_id": user_id
        }
    
    async def get_rejected_tracks(self, room_id: str) -> List[Dict[str, Any]]:
        """Получает список отклоненных треков"""
        return await self.moderation_repo.get_rejected_tracks(room_id)
    
    async def restore_rejected_track(
        self,
        room_id: str,
        token: str
    ) -> Dict[str, Any]:
        """
        Восстанавливает отклоненный трек в плейлист
        
        Returns:
            Информация о восстановленном треке
        """
        # Получаем трек из отклоненных
        track_data = await self.moderation_repo.get_rejected_track(room_id, token)
        if not track_data:
            raise ValueError("Трек не найден в списке отклоненных")
        
        # Проверяем на дубликаты
        file_hash = track_data.get("file")
        existing_index = await self.track_repo.find_track_by_hash(room_id, file_hash)
        if existing_index is not None:
            raise ValueError("Трек уже существует в плейлисте")
        
        # Добавляем трек в плейлист
        track_obj = {
            "title": track_data.get("title"),
            "file": file_hash,
            "added_by": track_data.get("added_by"),
            "user_id": track_data.get("user_id"),
            "status": "approved"
        }
        await self.track_repo.add_track(room_id, track_obj)
        
        # Удаляем из списка отклоненных
        await self.moderation_repo.remove_from_rejected(room_id, token)
        
        # Обновляем статус трека пользователя
        user_id = track_data.get("user_id")
        if user_id:
            await self.track_repo.update_user_track_status(user_id, room_id, token, "approved")
        
        return {
            "track": track_obj,
            "user_id": user_id
        }
    
    def _generate_token(self) -> str:
        """Генерирует токен для трека"""
        import secrets
        return secrets.token_hex(8)
