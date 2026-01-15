"""
Service для работы с комнатами
"""
from typing import Optional, List
from repositories.room_repository import RoomRepository
from utils.room_permissions import get_user_role, Role


class RoomService:
    """Сервис для работы с комнатами"""
    
    def __init__(self):
        self.room_repo = RoomRepository()
    
    async def get_user_role(self, user_id: int, room_id: str) -> Role:
        """Получает роль пользователя в комнате"""
        return await get_user_role(user_id, room_id)
    
    async def is_admin_or_owner(self, user_id: int, room_id: str) -> bool:
        """Проверяет, является ли пользователь админом или владельцем"""
        role = await self.get_user_role(user_id, room_id)
        return role in ("admin", "owner")
    
    async def can_add_tracks(self, user_id: int, room_id: str) -> bool:
        """Проверяет, может ли пользователь добавлять треки"""
        role = await self.get_user_role(user_id, room_id)
        return role in ("owner", "admin", "member")
    
    async def get_room_name(self, room_id: str) -> str:
        """Получает название комнаты"""
        name = await self.room_repo.get_room_name(room_id)
        return name or room_id
    
    async def is_moderation_enabled(self, room_id: str) -> bool:
        """Проверяет, включена ли модерация"""
        return await self.room_repo.is_moderation_enabled(room_id)
