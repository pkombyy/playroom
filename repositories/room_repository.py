"""
Repository для работы с комнатами
"""
from typing import Optional, List, Dict, Any
from repositories.base_repository import BaseRepository
from utils.redis_helper import redis_safe


class RoomRepository(BaseRepository):
    """Репозиторий для работы с комнатами"""
    
    def _room_name_key(self, room_id: str) -> str:
        return f"room:{room_id}:name"
    
    def _room_owner_key(self, room_id: str) -> str:
        return f"room:{room_id}:owner"
    
    def _room_members_key(self, room_id: str) -> str:
        return f"room:{room_id}:members"
    
    def _room_admins_key(self, room_id: str) -> str:
        return f"room:{room_id}:admins"
    
    def _room_banned_key(self, room_id: str) -> str:
        return f"room:{room_id}:banned"
    
    def _room_settings_key(self, room_id: str) -> str:
        return f"room:{room_id}:settings"
    
    def _room_moderation_key(self, room_id: str) -> str:
        return f"room:{room_id}:moderation"
    
    def _user_rooms_key(self, user_id: int) -> str:
        return f"user:{user_id}:rooms"
    
    def _user_admin_rooms_key(self, user_id: int) -> str:
        return f"user:{user_id}:admin_rooms"
    
    async def get_room_name(self, room_id: str) -> Optional[str]:
        """Получает название комнаты"""
        name_raw = await redis_safe(self.redis.get(self._room_name_key(room_id)))
        if not name_raw:
            return None
        if isinstance(name_raw, bytes):
            return name_raw.decode()
        return str(name_raw)
    
    async def set_room_name(self, room_id: str, name: str) -> bool:
        """Устанавливает название комнаты"""
        return await redis_safe(self.redis.set(self._room_name_key(room_id), name))
    
    async def get_room_owner(self, room_id: str) -> Optional[int]:
        """Получает ID владельца комнаты"""
        owner_raw = await redis_safe(self.redis.get(self._room_owner_key(room_id)))
        if not owner_raw:
            return None
        try:
            if isinstance(owner_raw, bytes):
                owner_raw = owner_raw.decode()
            return int(owner_raw)
        except Exception:
            return None
    
    async def set_room_owner(self, room_id: str, user_id: int) -> bool:
        """Устанавливает владельца комнаты"""
        return await redis_safe(self.redis.set(self._room_owner_key(room_id), str(user_id)))
    
    async def get_room_members(self, room_id: str) -> List[int]:
        """Получает список участников комнаты"""
        members = await self._set_members(self._room_members_key(room_id))
        return [int(m) for m in members if m.isdigit()]
    
    async def add_room_member(self, room_id: str, user_id: int) -> bool:
        """Добавляет участника в комнату"""
        await self._set_add(self._room_members_key(room_id), str(user_id))
        await self._set_add(self._user_rooms_key(user_id), room_id)
        return True
    
    async def remove_room_member(self, room_id: str, user_id: int) -> bool:
        """Удаляет участника из комнаты"""
        await self._set_remove(self._room_members_key(room_id), str(user_id))
        await self._set_remove(self._user_rooms_key(user_id), room_id)
        return True
    
    async def get_room_admins(self, room_id: str) -> List[int]:
        """Получает список админов комнаты"""
        admins = await self._set_members(self._room_admins_key(room_id))
        return [int(a) for a in admins if a.isdigit()]
    
    async def add_room_admin(self, room_id: str, user_id: int) -> bool:
        """Добавляет админа в комнату"""
        await self._set_add(self._room_admins_key(room_id), str(user_id))
        await self._set_add(self._room_members_key(room_id), str(user_id))
        await self._set_add(self._user_admin_rooms_key(user_id), room_id)
        await self._set_add(self._user_rooms_key(user_id), room_id)
        return True
    
    async def remove_room_admin(self, room_id: str, user_id: int) -> bool:
        """Удаляет админа из комнаты"""
        await self._set_remove(self._room_admins_key(room_id), str(user_id))
        await self._set_remove(self._user_admin_rooms_key(user_id), room_id)
        return True
    
    async def get_room_banned(self, room_id: str) -> List[int]:
        """Получает список заблокированных пользователей"""
        banned = await self._set_members(self._room_banned_key(room_id))
        return [int(b) for b in banned if b.isdigit()]
    
    async def ban_user(self, room_id: str, user_id: int) -> bool:
        """Блокирует пользователя"""
        await self._set_add(self._room_banned_key(room_id), str(user_id))
        await self.remove_room_member(room_id, user_id)
        await self.remove_room_admin(room_id, user_id)
        return True
    
    async def unban_user(self, room_id: str, user_id: int) -> bool:
        """Разблокирует пользователя"""
        await self._set_remove(self._room_banned_key(room_id), str(user_id))
        return True
    
    async def is_moderation_enabled(self, room_id: str) -> bool:
        """Проверяет, включена ли модерация"""
        moderation_raw = await redis_safe(self.redis.get(self._room_moderation_key(room_id)))
        if moderation_raw is None:
            return False
        if isinstance(moderation_raw, bytes):
            return moderation_raw == b"1"
        return str(moderation_raw) == "1"
    
    async def set_moderation(self, room_id: str, enabled: bool) -> bool:
        """Включает/выключает модерацию"""
        return await redis_safe(self.redis.set(self._room_moderation_key(room_id), "1" if enabled else "0"))
    
    async def get_user_rooms(self, user_id: int) -> List[str]:
        """Получает список комнат пользователя"""
        return await self._set_members(self._user_rooms_key(user_id))
    
    async def get_user_admin_rooms(self, user_id: int) -> List[str]:
        """Получает список комнат, где пользователь админ"""
        return await self._set_members(self._user_admin_rooms_key(user_id))
