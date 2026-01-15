"""
Базовый класс для репозиториев
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from config import redis
from utils.redis_helper import redis_safe
import json


class BaseRepository(ABC):
    """Базовый класс для всех репозиториев"""
    
    def __init__(self):
        self.redis = redis
    
    async def _get(self, key: str) -> Optional[Dict[str, Any]]:
        """Получает JSON объект из Redis"""
        data_raw = await redis_safe(self.redis.get(key))
        if not data_raw:
            return None
        try:
            if isinstance(data_raw, bytes):
                data_raw = data_raw.decode()
            return json.loads(data_raw)
        except Exception:
            return None
    
    async def _set(self, key: str, data: Dict[str, Any], ex: Optional[int] = None) -> bool:
        """Сохраняет JSON объект в Redis"""
        try:
            json_str = json.dumps(data, ensure_ascii=False)
            if ex:
                return await redis_safe(self.redis.set(key, json_str, ex=ex))
            return await redis_safe(self.redis.set(key, json_str))
        except Exception as e:
            print(f"❌ Ошибка сохранения в Redis {key}: {e}")
            return False
    
    async def _delete(self, key: str) -> bool:
        """Удаляет ключ из Redis"""
        return await redis_safe(self.redis.delete(key))
    
    async def _exists(self, key: str) -> bool:
        """Проверяет существование ключа"""
        return await redis_safe(self.redis.exists(key))
    
    async def _list_get(self, key: str, start: int = 0, end: int = -1) -> List[Dict[str, Any]]:
        """Получает список JSON объектов из Redis list"""
        items_raw = await redis_safe(self.redis.lrange(key, start, end))
        result = []
        for item_raw in (items_raw or []):
            if item_raw == "__deleted__":
                continue
            try:
                if isinstance(item_raw, bytes):
                    item_raw = item_raw.decode()
                result.append(json.loads(item_raw))
            except Exception:
                pass
        return result
    
    async def _list_add(self, key: str, data: Dict[str, Any]) -> int:
        """Добавляет JSON объект в Redis list"""
        json_str = json.dumps(data, ensure_ascii=False)
        return await redis_safe(self.redis.rpush(key, json_str))
    
    async def _list_remove(self, key: str, data: Dict[str, Any], count: int = 1) -> int:
        """Удаляет JSON объект из Redis list"""
        json_str = json.dumps(data, ensure_ascii=False)
        return await redis_safe(self.redis.lrem(key, count, json_str))
    
    async def _list_set(self, key: str, index: int, data: Dict[str, Any]) -> bool:
        """Устанавливает элемент списка по индексу"""
        json_str = json.dumps(data, ensure_ascii=False)
        return await redis_safe(self.redis.lset(key, index, json_str))
    
    async def _set_add(self, key: str, value: str) -> int:
        """Добавляет значение в Redis set"""
        return await redis_safe(self.redis.sadd(key, value))
    
    async def _set_remove(self, key: str, value: str) -> int:
        """Удаляет значение из Redis set"""
        return await redis_safe(self.redis.srem(key, value))
    
    async def _set_members(self, key: str) -> List[str]:
        """Получает все элементы из Redis set"""
        members_raw = await redis_safe(self.redis.smembers(key))
        return [
            m.decode() if isinstance(m, bytes) else str(m)
            for m in (members_raw or [])
        ]
    
    async def _set_contains(self, key: str, value: str) -> bool:
        """Проверяет наличие значения в Redis set"""
        return await redis_safe(self.redis.sismember(key, value))
