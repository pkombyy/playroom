"""
Утилиты для работы с ролями и правами в комнате
"""
from typing import Literal
from config import redis
from utils.redis_helper import redis_safe

Role = Literal["owner", "admin", "member", "banned"]


async def get_user_role(user_id: int, room_id: str) -> Role:
    """
    Получает роль пользователя в комнате.
    
    Returns:
        "owner", "admin", "member" или "banned"
        Если пользователь не найден ни в одной роли, возвращает "member" (по умолчанию)
    """
    # Проверяем владельца
    owner_raw = await redis_safe(redis.get(f"room:{room_id}:owner"))
    if owner_raw:
        owner_id = int(owner_raw.decode() if isinstance(owner_raw, bytes) else owner_raw)
        if owner_id == user_id:
            return "owner"
    
    # Проверяем заблокированных (ВАЖНО: проверяем ПЕРВЫМ после owner)
    is_banned = await redis_safe(redis.sismember(f"room:{room_id}:banned", str(user_id)))
    if is_banned:
        return "banned"
    
    # Проверяем админов
    is_admin = await redis_safe(redis.sismember(f"room:{room_id}:admins", str(user_id)))
    if is_admin:
        return "admin"
    
    # Проверяем участников
    is_member = await redis_safe(redis.sismember(f"room:{room_id}:members", str(user_id)))
    if is_member:
        return "member"
    
    # Если пользователь не найден ни в одной роли, он еще не был в комнате
    # Возвращаем "member" как дефолтную роль (может присоединиться)
    return "member"


async def is_admin_or_owner(user_id: int, room_id: str) -> bool:
    """Проверяет, является ли пользователь админом или владельцем"""
    role = await get_user_role(user_id, room_id)
    return role in ("admin", "owner")


async def can_add_tracks(user_id: int, room_id: str) -> bool:
    """Проверяет, может ли пользователь добавлять треки"""
    role = await get_user_role(user_id, room_id)
    return role in ("owner", "admin", "member")


async def set_user_role(user_id: int, room_id: str, role: Role):
    """
    Устанавливает роль пользователя в комнате.
    
    Args:
        user_id: ID пользователя
        room_id: ID комнаты
        role: Новая роль
    """
    user_id_str = str(user_id)
    
    # Удаляем из всех ролей
    await redis_safe(redis.srem(f"room:{room_id}:admins", user_id_str))
    await redis_safe(redis.srem(f"room:{room_id}:members", user_id_str))
    await redis_safe(redis.srem(f"room:{room_id}:banned", user_id_str))
    await redis_safe(redis.srem(f"user:{user_id}:admin_rooms", room_id))
    
    # Добавляем в нужную роль
    if role == "admin":
        await redis_safe(redis.sadd(f"room:{room_id}:admins", user_id_str))
        await redis_safe(redis.sadd(f"user:{user_id}:admin_rooms", room_id))
        await redis_safe(redis.sadd(f"room:{room_id}:members", user_id_str))
        await redis_safe(redis.sadd(f"user:{user_id}:rooms", room_id))
    elif role == "member":
        await redis_safe(redis.sadd(f"room:{room_id}:members", user_id_str))
        await redis_safe(redis.sadd(f"user:{user_id}:rooms", room_id))
    elif role == "banned":
        await redis_safe(redis.sadd(f"room:{room_id}:banned", user_id_str))
        # Удаляем из комнаты
        await redis_safe(redis.srem(f"room:{room_id}:members", user_id_str))
        await redis_safe(redis.srem(f"user:{user_id}:rooms", room_id))
        await redis_safe(redis.srem(f"user:{user_id}:admin_rooms", room_id))
    # owner не меняется через эту функцию


async def get_room_admins(room_id: str) -> list[int]:
    """Получает список админов комнаты"""
    admins_raw = await redis_safe(redis.smembers(f"room:{room_id}:admins"))
    return [
        int(a.decode() if isinstance(a, bytes) else a)
        for a in (admins_raw or [])
    ]


async def get_room_members(room_id: str) -> list[int]:
    """Получает список участников комнаты"""
    members_raw = await redis_safe(redis.smembers(f"room:{room_id}:members"))
    return [
        int(m.decode() if isinstance(m, bytes) else m)
        for m in (members_raw or [])
    ]


async def get_room_banned(room_id: str) -> list[int]:
    """Получает список заблокированных пользователей"""
    banned_raw = await redis_safe(redis.smembers(f"room:{room_id}:banned"))
    return [
        int(b.decode() if isinstance(b, bytes) else b)
        for b in (banned_raw or [])
    ]


async def get_room_settings(room_id: str) -> dict:
    """
    Получает настройки комнаты.
    
    Returns:
        dict с ключами:
        - moderation_enabled: bool - требуется ли подтверждение админа для треков
    """
    moderation_raw = await redis_safe(redis.get(f"room:{room_id}:moderation"))
    moderation_enabled = moderation_raw == b"1" if isinstance(moderation_raw, bytes) else bool(moderation_raw)
    
    return {
        "moderation_enabled": moderation_enabled
    }


async def set_room_moderation(room_id: str, enabled: bool):
    """Включает/выключает модерацию треков в комнате"""
    await redis_safe(redis.set(f"room:{room_id}:moderation", "1" if enabled else "0"))


async def is_moderation_enabled(room_id: str) -> bool:
    """Проверяет, включена ли модерация в комнате"""
    settings = await get_room_settings(room_id)
    return settings["moderation_enabled"]
