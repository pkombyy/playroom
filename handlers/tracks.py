import hashlib
import json
import secrets
from types import SimpleNamespace
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder
from handlers.rooms import open_room
from utils.storage import RoomContext
from utils.youtube import download_track
from config import redis
from utils.redis_helper import redis_safe

router = Router()


class TrackAdd(StatesGroup):
    waiting_for_query = State()


# --- Нажатие “Добавить трек” ---
@router.callback_query(F.data.startswith("addtrack:"))
async def add_track_to_room(callback: types.CallbackQuery, state: FSMContext):
    room_id = callback.data.split(":")[1] # type: ignore
    await state.update_data(room_id=room_id)
    await state.set_state(TrackAdd.waiting_for_query)
    await callback.message.edit_text( # type: ignore
        f"🎵 Введи название трека, который хочешь добавить в комнату <b>{room_id}</b>:"
    )


# --- Пользователь вводит запрос ---
@router.message(TrackAdd.waiting_for_query)
async def handle_track_query(message: types.Message, state: FSMContext):
    query = message.text.strip()  # type: ignore
    data = await state.get_data()
    room_id = data.get("room_id")

    await message.answer(f"🔍 Ищу трек <b>{query}</b>...")

    result = await download_track(query)
    if not result:
        await message.answer("⚠️ Не удалось найти или загрузить трек.")
        await state.clear()
        return

    # 👇 вот здесь изменено
    title = result["title"]
    audio_buf = result["buffer"]
    file_hash = result["hash"]
    print(f"🎯 title={title}, hash={file_hash}")

    # создаём временный ключ в redis
    import secrets, json
    from utils.redis_helper import redis_safe

    token = secrets.token_hex(4)
    cache_key = f"pending_track:{token}"
    track_data = {
        "room_id": room_id,
        "title": title,
        "file": file_hash,
        "user_id": message.from_user.id,  # type: ignore
        "added_by": message.from_user.full_name  # type: ignore
    }
    await redis_safe(redis.set(cache_key, json.dumps(track_data), ex=600))

    # 👇 создаём кнопки подтверждения / отмены
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Добавить", callback_data=f"confirm:{token}:public")
    kb.button(text="🤫 Анонимно", callback_data=f"confirm:{token}:anon")
    kb.button(text="❌ Отмена", callback_data="cancel_add")
    kb.adjust(2)
    kb.adjust(2)

    # 👇 используем mp3 из памяти
    input_file = types.BufferedInputFile(audio_buf.read(), filename=f"{title}.mp3")

    await message.answer_audio(
        audio=input_file,
        caption=f"🎧 Это твой трек?",
        title=title,
        reply_markup=kb.as_markup()
    )

    await state.clear()


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_track(callback: types.CallbackQuery):
    parts = callback.data.split(":")  # type: ignore
    token = parts[1]
    anon = len(parts) > 2 and parts[2] == "anon"
    cache_key = f"pending_track:{token}"

    data_raw = await redis_safe(redis.get(cache_key))
    if not data_raw:
        await callback.answer("⚠️ Истёк срок подтверждения трека.", show_alert=True)
        return

    data = json.loads(data_raw)
    room_id = data["room_id"]
    title = data["title"]
    file_hash = data["file"]
    user_id = data["user_id"]
    added_by = "анонимно" if anon else data["added_by"]

    print(f"🧩 confirm_track: room_id={room_id}, title={title}, file_hash={file_hash}")

    # --- защита от повторов ---
    existing_tracks_raw = await redis_safe(redis.lrange(f"room:{room_id}:tracks", 0, -1))
    for t_raw in existing_tracks_raw or []:
        t = json.loads(t_raw)
        if t.get("file") == file_hash or t.get("title").lower() == title.lower():
            await callback.answer("🚫 Этот трек уже есть в плейлисте.", show_alert=True)
            return

    # --- сохраняем трек ---
    track_obj = {
        "title": title,
        "file": file_hash,
        "added_by": added_by,
        "user_id": user_id
    }

    await redis_safe(redis.rpush(f"room:{room_id}:tracks", json.dumps(track_obj)))

    # --- уведомляем владельца + участников ---
    members_raw = await redis_safe(redis.smembers(f"room:{room_id}:members"))
    members = [int(m.decode() if isinstance(m, bytes) else m) for m in (members_raw or [])]

    owner = await redis_safe(redis.get(f"room:{room_id}:owner"))
    if owner:
        owner_id = int(owner)
        if owner_id not in members:
            members.append(owner_id)

    message_text = (
        f"🎵 В комнату <b>{room_id}</b> добавлен новый трек:\n"
        f"<b>{title}</b> от {added_by}"
    )

    for member_id in members:
        # не спамим отправителю
        if member_id == user_id:
            continue
        try:
            await callback.bot.send_message(member_id, message_text)  # type: ignore
        except Exception:
            pass

    # --- подтверждение пользователю ---
    await callback.answer("✅ Трек добавлен!")
    try:
        await callback.message.delete()  # type: ignore
    except Exception:
        pass

    # --- открываем последнюю страницу ---
    total_tracks = await redis_safe(redis.llen(f"room:{room_id}:tracks")) or 0
    per_page = 10
    last_page = max(0, (total_tracks - 1) // per_page)

    print(f"📄 открываем последнюю страницу: {last_page} для room_id={room_id}")

    # создаём поддельный callback с нужными атрибутами
    fake_callback = SimpleNamespace(
        data=f"roompage:{room_id}:{last_page}",
        from_user=callback.from_user,
        message=callback.message,
        bot=callback.bot
    )

    await open_room(fake_callback)


# --- Отмена ---
@router.callback_query(F.data == "cancel_add")
async def cancel_add(callback: types.CallbackQuery):
    await callback.answer("🚫 Отмена добавления.")
    room_id = await RoomContext.get_active_room(callback.from_user.id)
    if room_id:
        total_tracks = await redis_safe(redis.llen(f"room:{room_id}:tracks")) or 0
        per_page = 10
        last_page = max(0, (total_tracks - 1) // per_page)

        print(f"📄 открываем последнюю страницу: {last_page} для room_id={room_id}")

        # создаём поддельный callback с нужными атрибутами
        fake_callback = SimpleNamespace(
            data=f"roompage:{room_id}:{last_page}",
            from_user=callback.from_user,
            message=callback.message,
            bot=callback.bot
        )

        await open_room(fake_callback)
