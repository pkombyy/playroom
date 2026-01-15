"""
Handlers для работы с комнатами
Рефакторинг с использованием Repository и Service слоев
"""
import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Union, Set, cast

from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import redis, bot as bot_instance
from utils.google_drive import upload_to_drive
from utils.redis_helper import redis_safe
from utils.storage import RoomContext
from utils.youtube import CACHE_DIR
from utils.timezone import format_datetime, iso_now
from repositories.track_repository import TrackRepository
from repositories.room_repository import RoomRepository
from services.room_service import RoomService
from services.track_service import TrackService
from services.notification_service import NotificationService

# Инициализация сервисов и репозиториев
room_service = RoomService()
track_service = TrackService()
notification_service = NotificationService()
track_repo = TrackRepository()
room_repo = RoomRepository()

router = Router()

MAX_MSG_LEN = 4000

# -------- утилита построения клавы комнат --------
async def build_rooms_kb(user_id: int, page: int = 0, per_page: int = 5) -> types.InlineKeyboardMarkup:
    # Получаем комнаты через репозиторий
    rooms = await room_repo.get_user_rooms(user_id)
    admin_rooms_set = set(await room_repo.get_user_admin_rooms(user_id))

    start = page * per_page
    end = start + per_page

    kb = InlineKeyboardBuilder()

    # первая кнопка — создать комнату
    kb.button(text="➕ Создать комнату", callback_data="create_room")
    kb.adjust(1)  # ← она будет в своей строке

    # комнаты в столбик
    for rid in rooms[start:end]:
        name = await room_repo.get_room_name(rid) or "Без имени"
        star = "⭐ " if rid in admin_rooms_set else ""
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

    # Получаем треки через репозиторий
    tracks = await track_repo.get_all_tracks(room_id)

    # Получаем название комнаты через сервис
    room_name = await room_service.get_room_name(room_id)

    # Проверяем админа через сервис
    is_admin = await room_service.is_admin_or_owner(callback.from_user.id, room_id)  # type: ignore

    # пагинация
    per_page = 10
    total_tracks = len(tracks)
    total_pages = max(1, (total_tracks + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = start + per_page
    page_tracks = tracks[start:end]

    # 📊 считаем соавторов (с user_id для получения актуальных данных)
    author_data: dict[str, dict] = {}  # {author_name: {"count": int, "user_id": int}}
    anon_count = 0
    for t in tracks:
        author = t.get("added_by", "анонимно")
        user_id = t.get("user_id")
        
        if author.lower() == "анонимно" or not author or author.strip() == "":
            anon_count += 1
        else:
            if author not in author_data:
                author_data[author] = {"count": 0, "user_id": user_id}
            author_data[author]["count"] += 1

    # Получаем участников через репозиторий
    members = await room_repo.get_room_members(room_id)

    # текст заголовка
    text = f"🎧 <b>{room_name}</b>\n"
    text += f"📀 Треков всего: <b>{total_tracks}</b>\n\n"

    # соавторы
    if author_data or anon_count:
        text += "👥 <b>Соавторы плейлиста:</b>\n"
        sorted_authors = sorted(author_data.items(), key=lambda x: x[1]["count"], reverse=True)
        
        for author_name, data in sorted_authors:
            count = data["count"]
            user_id = data.get("user_id")
            
            # Если имя пустое или содержит только пробелы, получаем username
            display_name = author_name
            if not author_name or author_name.strip() == "" or author_name.strip() == "ㅤ":
                if user_id:
                    try:
                        user = await callback.bot.get_chat(user_id)  # type: ignore
                        display_name = user.username and f"@{user.username}" or (user.full_name or f"User {user_id}")
                    except Exception:
                        display_name = f"User {user_id}" if user_id else "Неизвестно"
                else:
                    display_name = "Неизвестно"
            else:
                # Очищаем имя от странных символов
                display_name = author_name.strip()
                # Удаляем невидимые символы и биди-маркеры
                display_name = ''.join(c for c in display_name if c.isprintable() and ord(c) < 0x10000)
            
            text += f"• {display_name} — {count}\n"
        
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
    kb.row(
        types.InlineKeyboardButton(text="🎵 Мои треки", callback_data=f"my_tracks:{room_id}")
    )
    if is_admin:
        kb.row(
            types.InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"room_settings:{room_id}")
        )
        kb.row(
            types.InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data=f"invite:{room_id}")
        )
        kb.row(
        types.InlineKeyboardButton(text="📢 Рассылка", callback_data=f"broadcast:{room_id}")
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


# @router.callback_query(F.data.startswith("broadcast:"))
# async def start_broadcast(callback: types.CallbackQuery):
#     room_id = callback.data.split(":")[1]  # type: ignore
#     is_admin = await redis_safe(redis.sismember(f"user:{callback.from_user.id}:admin_rooms", room_id))

#     if not is_admin:
#         await callback.answer("⛔ Только админ может делать рассылку.", show_alert=True)
#         return

#     await callback.message.answer( # type: ignore
#         f"📝 Введи текст рассылки для комнаты <b>{room_id}</b>.\n\n"
#         "Отправь сообщение сюда — я его перешлю всем участникам комнаты.",
#         parse_mode="HTML"
#     )

#     # сохраняем контекст — кто и в какой комнате пишет рассылку
#     await redis_safe(redis.set(f"broadcast_pending:{callback.from_user.id}", room_id))

# @router.message(F.text)
# async def handle_broadcast_message(message: types.Message):
#     key = f"broadcast_pending:{message.from_user.id}" # type: ignore
#     room_id_raw = await redis_safe(redis.get(key))

#     if not room_id_raw:
#         return  # не в режиме рассылки

#     room_id = room_id_raw.decode() if isinstance(room_id_raw, (bytes, bytearray)) else room_id_raw

#     # очищаем состояние
#     await redis_safe(redis.delete(key))

#     # получаем список участников
#     members_raw = await redis_safe(redis.smembers(f"room:{room_id}:members"))
#     members = [
#         int(m.decode()) if isinstance(m, (bytes, bytearray)) else int(m)
#         for m in (members_raw or [])
#     ]

#     await message.answer(f"🚀 Начинаю рассылку по {len(members)} участникам...")

#     sent = 0
#     failed = 0
#     for uid in members:
#         try:
#             await message.bot.send_message(uid, f"📢 <b>Сообщение от админа комнаты {room_id}</b>\n\n{message.text}", parse_mode="HTML") # type: ignore
#             sent += 1
#         except Exception:
#             failed += 1

#     await message.answer(f"✅ Рассылка завершена.\n📬 Отправлено: {sent}\n⚠️ Ошибок: {failed}")


# ---------- Просмотр информации о треке ----------
@router.callback_query(F.data.startswith("track:"))
async def view_track_info(callback: types.CallbackQuery):
    """Показывает информацию о треке и позволяет прослушать его"""
    parts = callback.data.split(":")  # type: ignore
    room_id = parts[1]
    track_index = int(parts[2])
    
    # Получаем трек через репозиторий
    track = await track_repo.get_track(room_id, track_index)
    if not track:
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return
    
    title = track.get("title", "Неизвестно")
    file_hash = track.get("file")
    added_by = track.get("added_by", "Неизвестно")
    user_id = track.get("user_id")
    added_at = track.get("added_at")
    moderated_at = track.get("moderated_at")
    status = track.get("status", "approved")
    
    # Форматируем даты через timezone утилиту
    added_date = format_datetime(added_at)
    moderated_date = format_datetime(moderated_at) if moderated_at else "Не модерировался"
    
    # Формируем текст
    text = f"🎵 <b>{title}</b>\n\n"
    text += f"👤 Добавил: <b>{added_by}</b>\n"
    text += f"📅 Дата добавления: <b>{added_date}</b>\n"
    text += f"📋 Дата модерации: <b>{moderated_date}</b>\n"
    text += f"📊 Статус: <b>{status}</b>\n"
    
    # Проверяем права админа
    is_admin = await room_service.is_admin_or_owner(callback.from_user.id, room_id)  # type: ignore
    
    kb = InlineKeyboardBuilder()
    
    # Кнопка прослушать трек
    if file_hash:
        audio_file = CACHE_DIR / f"{file_hash}.mp3"
        if audio_file.exists():
            kb.button(text="🎧 Прослушать", callback_data=f"play_track:{room_id}:{track_index}")
    
    # Для админов - кнопка изменения статуса
    if is_admin:
        kb.button(text="⚙️ Изменить статус", callback_data=f"change_track_status:{room_id}:{track_index}")
    
    kb.button(text="🔙 Назад к комнате", callback_data=f"room:{room_id}")
    kb.adjust(1)
    
    await callback.message.edit_text( # type: ignore
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


# ---------- Прослушивание трека ----------
@router.callback_query(F.data.startswith("play_track:"))
async def play_track(callback: types.CallbackQuery):
    """Отправляет аудиофайл для прослушивания"""
    parts = callback.data.split(":")  # type: ignore
    room_id = parts[1]
    track_index = int(parts[2])
    
    # Получаем трек через репозиторий
    track = await track_repo.get_track(room_id, track_index)
    if not track:
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return
    
    file_hash = track.get("file")
    title = track.get("title", "Трек")
    
    if not file_hash:
        await callback.answer("⚠️ Файл трека не найден.", show_alert=True)
        return
    
    audio_file = CACHE_DIR / f"{file_hash}.mp3"
    if not audio_file.exists():
        await callback.answer("⚠️ Аудиофайл не найден на сервере.", show_alert=True)
        return
    
    # Отправляем аудио
    try:
        with open(audio_file, "rb") as f:
            audio_data = f.read()
        input_file = types.BufferedInputFile(audio_data, filename=f"{title}.mp3")
        
        await callback.message.answer_audio( # type: ignore
            audio=input_file,
            title=title,
            caption=f"🎧 {title}"
        )
        await callback.answer("✅ Трек отправлен")
    except Exception as e:
        print(f"❌ Ошибка при отправке трека: {e}")
        await callback.answer("⚠️ Ошибка при отправке трека.", show_alert=True)


# ---------- Изменение статуса трека ----------
@router.callback_query(F.data.startswith("change_track_status:"))
async def change_track_status(callback: types.CallbackQuery):
    """Позволяет админу изменить статус трека"""
    parts = callback.data.split(":")  # type: ignore
    room_id = parts[1]
    track_index = int(parts[2])
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Получаем трек через репозиторий
    track = await track_repo.get_track(room_id, track_index)
    if not track:
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return
    
    title = track.get("title", "Неизвестно")
    status = track.get("status", "approved")
    user_id = track.get("user_id")
    
    text = f"⚙️ <b>Изменение статуса трека</b>\n\n"
    text += f"🎵 <b>{title}</b>\n"
    text += f"📊 Текущий статус: <b>{status}</b>\n\n"
    text += "Выберите новое действие:"
    
    kb = InlineKeyboardBuilder()
    
    # Если трек одобрен, можно отклонить
    if status == "approved":
        kb.button(text="❌ Отклонить трек", callback_data=f"admin_reject_track:{room_id}:{track_index}")
    
    # Если трек отклонен, можно одобрить
    if status == "rejected":
        kb.button(text="✅ Одобрить трек", callback_data=f"admin_approve_track:{room_id}:{track_index}")
    
    kb.button(text="🔙 Назад к треку", callback_data=f"track:{room_id}:{track_index}")
    kb.adjust(1)
    
    await callback.message.edit_text( # type: ignore
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


# ---------- Админ отклоняет трек из плейлиста ----------
@router.callback_query(F.data.startswith("admin_reject_track:"))
async def admin_reject_track(callback: types.CallbackQuery):
    """Админ отклоняет трек и удаляет его из плейлиста"""
    parts = callback.data.split(":")  # type: ignore
    room_id = parts[1]
    track_index = int(parts[2])
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Получаем трек через репозиторий
    track = await track_repo.get_track(room_id, track_index)
    if not track:
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return
    
    title = track.get("title")
    file_hash = track.get("file")
    user_id = track.get("user_id")
    
    # Удаляем трек из плейлиста через сервис
    await track_repo.remove_track(room_id, track_index)
    
    # Обновляем статус трека пользователя
    user_tracks = await track_repo.get_user_tracks(user_id, room_id)
    for user_track in user_tracks:
        if user_track.get("file") == file_hash:
            await track_repo.update_user_track_status(
                user_id, room_id, user_track.get("token"), "rejected"
            )
            break
    
    # Уведомляем пользователя через сервис
    await notification_service.notify_track_rejected(user_id, room_id, title)
    
    await callback.answer("❌ Трек отклонен и удален из плейлиста")
    
    # Возвращаемся к комнате
    fake_callback = SimpleNamespace(
        data=f"room:{room_id}",
        from_user=callback.from_user,
        message=callback.message,
        bot=callback.bot
    )
    await open_room(fake_callback)


# ---------- Админ одобряет отклоненный трек ----------
@router.callback_query(F.data.startswith("admin_approve_track:"))
async def admin_approve_track(callback: types.CallbackQuery):
    """Админ одобряет отклоненный трек и добавляет его в плейлист"""
    parts = callback.data.split(":")  # type: ignore
    room_id = parts[1]
    track_index = int(parts[2])
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Получаем трек через репозиторий
    track = await track_repo.get_track(room_id, track_index)
    if not track:
        await callback.answer("⚠️ Трек не найден в плейлисте.", show_alert=True)
        return
    
    title = track.get("title")
    user_id = track.get("user_id")
    
    # Обновляем статус трека через сервис
    await track_service.update_track_status(room_id, track_index, "approved", user_id)
    
    # Уведомляем пользователя через сервис
    await notification_service.notify_track_approved(user_id, room_id, title)
    
    await callback.answer("✅ Трек одобрен")
    
    # Возвращаемся к просмотру трека с обновленной информацией
    fake_callback = SimpleNamespace(
        data=f"track:{room_id}:{track_index}",
        from_user=callback.from_user,
        message=callback.message,
        bot=callback.bot
    )
    await view_track_info(fake_callback)


# ---------- экспорт архива (максимальное сжатие + локальная папка) ----------
@router.callback_query(F.data.startswith("export:"))
async def export_playlist(callback: types.CallbackQuery):
    import io, zipfile, json, shutil
    from pathlib import Path
    from mutagen.mp3 import MP3
    from mutagen.id3._util import ID3NoHeaderError
    from utils.redis_helper import redis_safe
    from config import redis

    await callback.answer("⏳ Архив формируется, подождите...", show_alert=False)
    room_id = callback.data.split(":")[1]  # type: ignore

    # ---------- утилита: экспорт папки комнаты ----------
    async def export_room_to_folder(room_id: str) -> Path:
        """
        Собирает все mp3-файлы комнаты в отдельную папку exports/{room_id}/
        Возвращает путь к итоговой папке.
        """
        EXPORT_DIR = Path("exports")
        CACHE_DIR = Path("tmp/music_cache")

        EXPORT_DIR.mkdir(exist_ok=True)
        room_folder = EXPORT_DIR / room_id

        if room_folder.exists():
            shutil.rmtree(room_folder)
        room_folder.mkdir()

        # получаем треки через репозиторий
        tracks = await track_repo.get_all_tracks(room_id)

        if not tracks:
            raise ValueError(f"Комната {room_id} пуста — треков нет.")

        copied = 0
        skipped = 0
        for t in tracks:
            file_hash = t.get("file")
            title = t.get("title", file_hash)
            src = CACHE_DIR / f"{file_hash}.mp3"

            if not src.exists():
                skipped += 1
                continue

            safe_name = "".join(c for c in title if c.isalnum() or c in " _-").strip() or file_hash
            dst = room_folder / f"{safe_name}.mp3"

            shutil.copy2(src, dst)
            copied += 1

        print(f"[export] Room {room_id}: copied {copied}, skipped {skipped}")
        return room_folder

    # ---------- экспорт архива ----------
    try:
        room_folder = await export_room_to_folder(room_id)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return
    except Exception as e:
        print(f"[export] Ошибка при создании папки экспорта: {e}")
        await callback.answer("❌ Ошибка при создании архива.", show_alert=True)
        return

    # --- Параметры архива ---
    # Увеличиваем размер частей для большего количества треков (более 400)
    MAX_SIZE_MB = 48  # Максимальный размер файла в Telegram
    MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024
    part = 1

    def strip_tags(mp3_path: Path) -> bytes:
        """Удаляем ID3-теги и возвращаем чистый аудиопоток для лучшего сжатия."""
        try:
            audio = MP3(mp3_path)
            audio.delete()  # удаляем ID3-теги для уменьшения размера
            buf = io.BytesIO()
            audio.save(buf)
            return buf.getvalue()
        except ID3NoHeaderError:
            with open(mp3_path, "rb") as f:
                return f.read()

    # --- Сбор архива с максимальным сжатием ---
    current_buf = io.BytesIO()
    current_zip = zipfile.ZipFile(
        current_buf,
        "w",
        compression=zipfile.ZIP_LZMA,  # LZMA - максимальное сжатие
        compresslevel=9  # Максимальный уровень сжатия
    )

    mp3_files = sorted(room_folder.glob("*.mp3"))  # Сортируем для предсказуемости
    total_files = len(mp3_files)
    
    if total_files == 0:
        await callback.answer("⚠️ Нет треков для экспорта.", show_alert=True)
        try:
            shutil.rmtree(room_folder)
        except Exception:
            pass
        return
    
    try:
        for idx, mp3_path in enumerate(mp3_files, 1):
            try:
                data = strip_tags(mp3_path)
                # Используем относительный путь для лучшего сжатия
                current_zip.writestr(mp3_path.name, data, compress_type=zipfile.ZIP_LZMA)
            except Exception as e:
                print(f"[export] Ошибка при обработке {mp3_path.name}: {e}")
                continue  # Пропускаем проблемный файл

            # Проверяем размер архива (с запасом для заголовков)
            current_size = current_buf.tell()
            if current_size >= MAX_SIZE_BYTES * 0.95:  # 95% от максимума для запаса
                current_zip.close()
                current_buf.seek(0)
                await callback.message.answer_document(  # type: ignore
                    types.BufferedInputFile(current_buf.read(), filename=f"{room_id}_part{part}.zip"),
                    caption=f"📦 Часть {part} ({idx}/{total_files} треков)"
                )
            part += 1
            current_buf = io.BytesIO()
            current_zip = zipfile.ZipFile(
                current_buf,
                "w",
                compression=zipfile.ZIP_LZMA,
                compresslevel=9
            )

        # --- Финальный архив ---
        if current_buf.tell() > 0:  # Если есть данные в буфере
            current_zip.close()
            current_buf.seek(0)
            await callback.message.answer_document(  # type: ignore
                types.BufferedInputFile(current_buf.read(), filename=f"{room_id}_part{part}.zip"),
                caption=f"📦 Финальная часть архива ({total_files} треков всего)"
            )

        # Удаляем временную папку после экспорта
        try:
            shutil.rmtree(room_folder)
        except Exception as e:
            print(f"[export] Не удалось удалить временную папку: {e}")
        
        # Уведомляем только запросившего пользователя
        await callback.message.answer( # type: ignore
            f"✅ Архив комнаты готов!\n📦 Всего частей: {part}\n🎵 Треков: {total_files}",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"[export] Критическая ошибка при создании архива: {e}")
        import traceback
        traceback.print_exc()
        try:
            current_zip.close()
        except Exception:
            pass
        try:
            shutil.rmtree(room_folder)
        except Exception:
            pass
        await callback.answer("❌ Ошибка при создании архива.", show_alert=True)

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
