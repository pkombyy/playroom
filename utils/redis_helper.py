# === Безопасный хелпер для Redis ===
from typing import Any


async def redis_safe(coro: Any) -> Any:
    """Обёртка, чтобы работать и с redis<5, и с redis>=5."""
    if hasattr(coro, "__await__"):
        return await coro
    return coro