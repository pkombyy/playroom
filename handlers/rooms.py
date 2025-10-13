import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Union, Set, cast

from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import redis
from utils.google_drive import upload_to_drive
from utils.redis_helper import redis_safe
from utils.storage import RoomContext

router = Router()

MAX_MSG_LEN = 4000

# -------- утилита построения клавы комнат --------
async def build_rooms_kb(user_id: int, page: int = 0, per_page: int = 5) -> types.InlineKeyboardMarkup:
    rooms_raw: Union[Set[bytes], Set[str]] = await redis_safe(redis.smembers(f"user:{user_id}:rooms"))
    admin_raw: Union[Set[bytes], Set[str]] = await redis_safe(redis.smembers(f"user:{user_id}:admin_rooms"))

    rooms = [r.decode() if isinstance(r, (bytes, bytearray)) else str(r) for r in (rooms_raw or [])]
    admin_rooms = {r.decode() if isinstance(r, (bytes, bytearray)) else str(r) for r in (admin_raw or [])}

    start = page * per_page
    end = start + per_page

    kb = InlineKeyboardBuilder()

    # первая кнопка — создать комнату
    kb.button(text="➕ Создать комнату", callback_data="create_room")
    kb.adjust(1)  # ← она будет в своей строке

    # комнаты в столбик
    for rid in rooms[start:end]:
        name_raw = await redis_safe(redis.get(f"room:{rid}:name"))
        name = name_raw.decode() if isinstance(name_raw, (bytes, bytearray)) else str(name_raw or "Без имени")
        star = "⭐ " if rid in admin_rooms else ""
        kb.button(text=f"{star}{name}", callback_data=f"room:{rid}")

    kb.adjust(1)  # ← каждая комната — отдельная строка

    # пагинация внизу
    if len(rooms) > per_page:
        kb.row(
            types.InlineKeyboardButton(text="⬅️", callback_data=f"page:{page-1}" if page > 0 else "noop"),
            types.InlineKeyboardButton(text=f"{page+1}/{(len(rooms)//per_page)+1}", callback_data="noop"),
            types.InlineKeyboardButton(text="➡️", callback_data=f"page:{page+1}" if end < len(rooms) else "noop"),
        )

    return kb.as_markup()


# -------- “Мои комнаты” --------
@router.callback_query(F.data == "rooms")
async def show_rooms(cb: types.CallbackQuery):
    markup = await build_rooms_kb(cb.from_user.id, page=0)
    await RoomContext.clear_active_room(cb.from_user.id)
    msg: types.Message = cast(types.Message, cb.message)
    await msg.edit_text("🌌 Твои комнаты:", reply_markup=markup)


# -------- пагинация --------
@router.callback_query(F.data.startswith("page:"))
async def rooms_page(cb: types.CallbackQuery):
    page_str = cb.data.split(":")[1] # type: ignore
    try:
        page = int(page_str)
    except ValueError:
        return
    if page < 0:
        page = 0
    markup = await build_rooms_kb(cb.from_user.id, page=page)
    msg: types.Message = cast(types.Message, cb.message)
    await msg.edit_text("🌌 Твои комнаты:", reply_markup=markup)

def build_page_nav(room_id: str, current_page: int, total_pages: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()

    # показываем максимум 5 номеров
    window = 5
    start = max(0, current_page - window // 2)
    end = min(total_pages, start + window)

    # если ближе к концу, сдвигаем окно
    if end - start < window:
        start = max(0, end - window)

    # кнопка "влево"
    if current_page > 0 and total_pages > window:
        kb.button(text="⬅️", callback_data=f"roompage:{room_id}:{current_page - 1}")

    # номера страниц
    for i in range(start, end):
        label = f"[{i+1}]" if i == current_page else str(i+1)
        kb.button(text=label, callback_data=f"roompage:{room_id}:{i}")

    # кнопка "вправо"
    if current_page < total_pages - 1 and total_pages > window:
        kb.button(text="➡️", callback_data=f"roompage:{room_id}:{current_page + 1}")

    # всё в одну строку
    kb.adjust(window + 2)
    return kb

# ---------- открыть комнату (с пагинацией и нормальным видом) ----------
@router.callback_query(F.data.startswith(("room:", "roompage:")))
async def open_room(callback: types.CallbackQuery):
    data = callback.data.split(":")  # type: ignore
    room_id = data[1]
    page = int(data[2]) if len(data) > 2 else 0

    await RoomContext.set_active_room(callback.from_user.id, room_id)

    # треки
    tracks_raw = await redis_safe(redis.lrange(f"room:{room_id}:tracks", 0, -1))
    tracks = [
        json.loads(t)
        for t in (tracks_raw or [])
        if t and t != "__deleted__"
    ]

    # имя комнаты
    name_raw = await redis_safe(redis.get(f"room:{room_id}:name"))
    room_name = (
        name_raw.decode()
        if isinstance(name_raw, (bytes, bytearray))
        else str(name_raw or room_id)
    )

    # проверяем админа
    is_admin = await redis_safe(
        redis.sismember(f"user:{callback.from_user.id}:admin_rooms", room_id)
    )

    # пагинация
    per_page = 10
    total_tracks = len(tracks)
    total_pages = max(1, (total_tracks + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = start + per_page
    page_tracks = tracks[start:end]

    # 📊 считаем соавторов
    author_counts: dict[str, int] = {}
    anon_count = 0
    for t in tracks:
        author = t.get("added_by", "анонимно")
        if author.lower() == "анонимно":
            anon_count += 1
        else:
            author_counts[author] = author_counts.get(author, 0) + 1

    # 👥 участники комнаты
    members_raw = await redis_safe(redis.smembers(f"room:{room_id}:members"))
    members = [
        int(m.decode()) if isinstance(m, (bytes, bytearray)) else int(m)
        for m in (members_raw or [])
    ]

    # текст заголовка
    text = f"🎧 <b>{room_name}</b>\n"
    text += f"📀 Треков всего: <b>{total_tracks}</b>\n\n"

    # соавторы
    if author_counts or anon_count:
        text += "👥 <b>Соавторы плейлиста:</b>\n"
        sorted_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)
        for author, count in sorted_authors:
            text += f"• {author} — {count}\n"
        if anon_count:
            text += f"• 🤫 Анонимно — {anon_count}\n"
        text += "\n"

    # участники
    if members:
        text += "<b>Участники комнаты:</b>\n"
        for uid in members:
            try:
                user = await callback.bot.get_chat(uid)  # type: ignore
                name = user.username and f"@{user.username}" or user.full_name
                text += f"• {name}\n"
            except Exception:
                text += f"• 👤 {uid}\n"
        text += "\n"

    # плейлист
    if not page_tracks:
        text += "🎶 Плейлист пуст."

    # клавиатура
    kb = InlineKeyboardBuilder()

    # треки вертикально — по одной кнопке в строке
    for i, t in enumerate(page_tracks, start=start):
        kb.button(
            text=f"🎵 {t['title']}",
            callback_data=f"track:{room_id}:{i}"
        )
    kb.adjust(1)  # 👈 делает вертикальный список

    if total_pages > 1:
        nav = build_page_nav(room_id, page, total_pages)
        for row in nav.export():  # 👈 аккуратно добавляем ряды навигации
            kb.row(*row)

    # управление
    kb.row(
        types.InlineKeyboardButton(text="➕ Добавить трек", callback_data=f"addtrack:{room_id}"),
        types.InlineKeyboardButton(text="📦 Экспортировать", callback_data=f"export:{room_id}")
    )
    if is_admin:
        kb.row(
            types.InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data=f"invite:{room_id}")
        )
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="rooms"))

    try:
        await callback.message.edit_text( # type: ignore
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
    except Exception:
        await callback.message.answer( # type: ignore
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("track:"))
async def show_track(callback: types.CallbackQuery):
    _, room_id, idx = callback.data.split(":")  # type: ignore
    idx = int(idx)

    tracks_raw = await redis_safe(redis.lrange(f"room:{room_id}:tracks", 0, -1))
    tracks = [json.loads(t) for t in (tracks_raw or []) if t and t != "__deleted__"]

    if idx >= len(tracks):
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return

    t = tracks[idx]
    title = t.get("title", "Без названия")
    added_by = t.get("added_by", "анонимно")
    file_hash = t.get("file")

    mp3_path = Path("tmp/music_cache") / f"{file_hash}.mp3"
    if not mp3_path.exists():
        await callback.answer("❌ Файл не найден в кэше.", show_alert=True)
        return

    # кнопка "Назад" возвращает на нужную страницу
    page = idx // 10
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"roompage:{room_id}:{page}")

    # читаем файл и отправляем как аудио
    with open(mp3_path, "rb") as f:
        buf = io.BytesIO(f.read())

    await callback.message.delete() # type: ignore
    await callback.message.answer_audio( # type: ignore
        types.BufferedInputFile(buf.read(), filename=f"{title}.mp3"),
        title=title,
        caption=f"👤 Добавил: {added_by}",
        reply_markup=kb.as_markup()
    )

# ---------- экспорт архива ----------
@router.callback_query(F.data.startswith("export:"))
async def export_playlist(callback: types.CallbackQuery):
    await callback.answer("⏳ Архив формируется, подождите...", show_alert=False)
    room_id = callback.data.split(":")[1]  # type: ignore

    tracks_raw = await redis_safe(redis.lrange(f"room:{room_id}:tracks", 0, -1))
    tracks = [json.loads(t) for t in (tracks_raw or []) if t and t != "__deleted__"]

    if not tracks:
        await callback.answer("🎶 Плейлист пуст, нечего экспортировать.", show_alert=True)
        return

    MAX_SIZE_MB = 48
    current_buf = io.BytesIO()
    current_zip = zipfile.ZipFile(current_buf, "w", compression=zipfile.ZIP_DEFLATED)
    total_size = 0
    part = 1

    for t in tracks:
        file_hash = t.get("file")
        title = t.get("title", file_hash)
        mp3_path = Path("tmp/music_cache") / f"{file_hash}.mp3"

        if not mp3_path.exists():
            continue

        with open(mp3_path, "rb") as f:
            data = f.read()
            size_mb = len(data) / (1024 * 1024)

            if total_size + size_mb > MAX_SIZE_MB:
                current_zip.close()
                current_buf.seek(0)
                await callback.message.answer_document( # type: ignore
                    types.BufferedInputFile(current_buf.read(), filename=f"{room_id}_part{part}.zip"),
                    caption=f"📦 Часть {part}"
                )
                # новая пачка
                current_buf = io.BytesIO()
                current_zip = zipfile.ZipFile(current_buf, "w", compression=zipfile.ZIP_DEFLATED)
                part += 1
                total_size = 0

            current_zip.writestr(f"{title}.mp3", data)
            total_size += size_mb

    current_zip.close()
    current_buf.seek(0)
    await callback.message.answer_document( # type: ignore
        types.BufferedInputFile(current_buf.read(), filename=f"{room_id}_part{part}.zip"),
        caption=f"📦 Финальная часть архива комнаты"
    )

# ---------- очистка плейлиста ----------
@router.callback_query(F.data.startswith("clear_confirm:"))
async def confirm_clear(callback: types.CallbackQuery):
    room_id = callback.data.split(":")[1] # type: ignore
    is_admin = await redis_safe(redis.sismember(f"user:{callback.from_user.id}:admin_rooms", room_id))

    if not is_admin:
        await callback.answer("⛔ Только админ может очищать плейлист.", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, очистить", callback_data=f"clear:{room_id}")
    kb.button(text="❌ Отмена", callback_data=f"room:{room_id}")
    kb.adjust(2)

    await callback.message.edit_text( # type: ignore
        f"⚠️ Уверен, что хочешь удалить <b>все треки</b> из комнаты <b>{room_id}</b>?\n"
        "Это действие необратимо.",
        reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("clear:"))
async def clear_playlist(callback: types.CallbackQuery):
    room_id = callback.data.split(":")[1] # type: ignore
    is_admin = await redis_safe(redis.sismember(f"user:{callback.from_user.id}:admin_rooms", room_id))

    if not is_admin:
        await callback.answer("⛔ Только админ может очищать плейлист.", show_alert=True)
        return

    await redis_safe(redis.delete(f"room:{room_id}:tracks"))
    await callback.message.edit_text(f"💨 Плейлист комнаты <b>{room_id}</b> успешно очищен!") # type: ignore

    # уведомим участников
    members = await redis_safe(redis.smembers(f"room:{room_id}:members"))
    for m in members or []:
        try:
            uid = int(m.decode() if isinstance(m, bytes) else m)
            if uid != callback.from_user.id:
                await callback.bot.send_message(uid, f"🧹 Плейлист комнаты <b>{room_id}</b> был очищен админом.") # type: ignore
        except Exception:
            pass


# ---------- генерация рефералки ----------
@router.callback_query(F.data.startswith("invite:"))
async def invite_link(callback: types.CallbackQuery):
    room_id = callback.data.split(":")[1] # type: ignore
    is_admin = await redis_safe(redis.sismember(f"user:{callback.from_user.id}:admin_rooms", room_id))

    if not is_admin:
        await callback.answer("⛔ Только админ может создавать рефералку.", show_alert=True)
        return

    me = await callback.bot.me() # type: ignore
    username = me.username
    deep_link = f"https://t.me/{username}?start={room_id}"

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"room:{room_id}")

    await callback.message.edit_text( # type: ignore
        f"🔗 Реферальная ссылка для комнаты:\n<code>{deep_link}</code>\n\n"
        "Отправь её друзьям — они смогут присоединиться к твоей комнате 😉",
        reply_markup=kb.as_markup()
    )
