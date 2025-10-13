from aiogram import Router, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import redis
from utils.redis_helper import redis_safe

router = Router()

@router.message(CommandStart())
async def start_ref(message: types.Message, command: CommandStart):
    """
    /start и /start <room_id>.
    Если есть room_id — подключаем юзера к комнате.
    На экране — только одна кнопка: "Мои комнаты".
    """
    user_id = message.from_user.id # type: ignore
    room_id = command.args  # type: ignore # может быть None

    # одна единственная кнопка
    kb = InlineKeyboardBuilder()
    kb.button(text="🎶 Мои комнаты", callback_data="rooms")
    markup = kb.as_markup()

    if room_id:
        exists = await redis_safe(redis.get(f"room:{room_id}:name"))
        if exists:
            name = exists.decode() if isinstance(exists, (bytes, bytearray)) else str(exists)
            await redis_safe(redis.sadd(f"room:{room_id}:members", user_id))
            await redis_safe(redis.sadd(f"user:{user_id}:rooms", room_id))

            await message.answer(
                f"🎧 Ты присоединился к комнате <b>{name}</b>!",
                reply_markup=markup,
            )
            return
        else:
            await message.answer("❌ Такой комнаты не существует.", reply_markup=markup)
            return

    await message.answer(
        "👋 Привет! Добро пожаловать в <b>PlayRoom</b> 🎵",
        reply_markup=markup,
    )
