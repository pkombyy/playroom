from aiogram import Router, types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import redis
from utils.redis_helper import redis_safe  # 👈 вынеси redis_safe в utils/helpers.py
import uuid
import json

router = Router()


class CreateRoom(StatesGroup):
    waiting_for_name = State()


# --- Обработка нажатия "Создать комнату" ---
@router.callback_query(F.data == "create_room")
async def create_room_start(callback: types.CallbackQuery, state: FSMContext):
    message = callback.message
    await message.edit_text("📝 Введи название новой комнаты:") # type: ignore
    await state.set_state(CreateRoom.waiting_for_name)


# --- Пользователь вводит имя комнаты ---
@router.message(CreateRoom.waiting_for_name)
async def create_room_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    room_name = message.text.strip() # type: ignore

    # генерим уникальный room_id
    room_id = str(uuid.uuid4())[:8]

    # сохраняем в Redis
    await redis_safe(redis.set(f"room:{room_id}:name", room_name))
    await redis_safe(redis.set(f"room:{room_id}:owner", user_id))
    await redis_safe(redis.sadd(f"user:{user_id}:rooms", room_id))
    await redis_safe(redis.sadd(f"user:{user_id}:admin_rooms", room_id))
    await redis_safe(redis.sadd(f"room:{room_id}:members", user_id))

    # формируем фейковую реферальную ссылку
    ref_link = f"https://t.me/{(await message.bot.me()).username}?start={room_id}" # type: ignore

    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Вернуться к комнатам", callback_data="rooms")

    text = (
        f"✅ Комната <b>{room_name}</b> создана!\n\n"
        f"👑 Ты — админ этой комнаты.\n"
        f"🔗 Реферальная ссылка для приглашения участников:\n"
        f"<code>{ref_link}</code>"
    )

    await message.answer(text, reply_markup=kb.as_markup())
    await state.clear()
