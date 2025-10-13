from config import redis
from utils.redis_helper import redis_safe


class RoomContext:
    """Хранение активной комнаты пользователя."""

    @staticmethod
    async def set_active_room(user_id: int, room_id: str):
        ok = await redis.set(f"user:{user_id}:active_room", room_id)
        if not ok:
            print(f"⚠️ Не удалось сохранить активную комнату для пользователя {user_id}")
            
    @staticmethod
    async def get_active_room(user_id: int) -> str | None:
        val = await redis_safe(redis.get(f"user:{user_id}:active_room"))
        if not val:
            return None
        return val.decode() if isinstance(val, bytes) else str(val)

    @staticmethod
    async def clear_active_room(user_id: int):
        await redis_safe(redis.delete(f"user:{user_id}:active_room"))
