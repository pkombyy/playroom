from aiogram import Router, types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import redis
from utils.redis_helper import redis_safe
from utils.room_permissions import set_room_moderation
import uuid
import json

router = Router()


class CreateRoom(StatesGroup):
    waiting_for_name = State()
    waiting_for_moderation = State()


# --- Обработка нажатия "Создать комнату" ---
@router.callback_query(F.data == "create_room")
async def create_room_start(callback: types.CallbackQuery, state: FSMContext):
    message = callback.message
    await message.edit_text("📝 Введи название новой комнаты:") # type: ignore
    await state.set_state(CreateRoom.waiting_for_name)


# --- Пользователь вводит имя комнаты ---
@router.message(CreateRoom.waiting_for_name)
async def create_room_name(message: types.Message, state: FSMContext):
    room_name = message.text.strip() # type: ignore
    await state.update_data(room_name=room_name)
    
    # Спрашиваем про модерацию
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, нужна модерация", callback_data="moderation:yes")
    kb.button(text="❌ Нет, без модерации", callback_data="moderation:no")
    kb.adjust(1)
    
    await message.answer(
        f"📝 Название комнаты: <b>{room_name}</b>\n\n"
        "🔐 Нужна ли модерация треков?\n"
        "При включенной модерации треки будут добавляться только после подтверждения администратором.",
        reply_markup=kb.as_markup()
    )
    await state.set_state(CreateRoom.waiting_for_moderation)


# --- Выбор режима модерации ---
@router.callback_query(CreateRoom.waiting_for_moderation, F.data.startswith("moderation:"))
async def create_room_moderation(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    room_name = data.get("room_name")
    user_id = callback.from_user.id # type: ignore
    
    moderation_enabled = callback.data.split(":")[1] == "yes" # type: ignore
    
    # генерим уникальный room_id
    room_id = str(uuid.uuid4())[:8]

    # сохраняем в Redis
    await redis_safe(redis.set(f"room:{room_id}:name", room_name))
    await redis_safe(redis.set(f"room:{room_id}:owner", user_id))
    await redis_safe(redis.sadd(f"user:{user_id}:rooms", room_id))
    await redis_safe(redis.sadd(f"user:{user_id}:admin_rooms", room_id))
    await redis_safe(redis.sadd(f"room:{room_id}:members", user_id))
    await redis_safe(redis.sadd(f"room:{room_id}:admins", user_id))
    
    # Устанавливаем режим модерации
    await set_room_moderation(room_id, moderation_enabled)

    # формируем фейковую реферальную ссылку
    ref_link = f"https://t.me/{(await callback.bot.me()).username}?start={room_id}" # type: ignore

    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Вернуться к комнатам", callback_data="rooms")

    moderation_text = "включена" if moderation_enabled else "выключена"
    text = (
        f"✅ Комната <b>{room_name}</b> создана!\n\n"
        f"👑 Ты — владелец этой комнаты.\n"
        f"🔐 Модерация треков: <b>{moderation_text}</b>\n"
        f"🔗 Реферальная ссылка для приглашения участников:\n"
        f"<code>{ref_link}</code>"
    )

    await callback.message.edit_text(text, reply_markup=kb.as_markup()) # type: ignore
    await state.clear()
