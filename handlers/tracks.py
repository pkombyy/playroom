"""
Handlers для работы с треками
Рефакторинг с использованием Repository и Service слоев
"""
import json
import secrets
from types import SimpleNamespace
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder
from handlers.rooms import open_room
from utils.youtube import download_track, CACHE_DIR
from config import redis, bot as bot_instance, TG_MAX_FILE_BYTES
from utils.redis_helper import redis_safe
from services.track_service import TrackService
from services.moderation_service import ModerationService
from services.room_service import RoomService
from services.notification_service import NotificationService
from utils.timezone import iso_now, format_datetime

router = Router()

# Инициализация сервисов и репозиториев
from repositories.track_repository import TrackRepository
track_service = TrackService()
moderation_service = ModerationService()
room_service = RoomService()
notification_service = NotificationService()
track_repo = TrackRepository()


class TrackAdd(StatesGroup):
    waiting_for_query = State()


# --- Нажатие "Добавить трек" ---
@router.callback_query(F.data.startswith("addtrack:"))
async def add_track_to_room(callback: types.CallbackQuery, state: FSMContext):
    room_id = callback.data.split(":")[1] # type: ignore
    user_id = callback.from_user.id  # type: ignore
    
    # Ограничения на добавление треков убраны - любой пользователь может добавлять треки
    
    # Получаем название комнаты
    room_name = await room_service.get_room_name(room_id)
    
    await state.update_data(room_id=room_id)
    await state.set_state(TrackAdd.waiting_for_query)
    await callback.message.edit_text( # type: ignore
        f"🎵 Введи название трека, который хочешь добавить в комнату <b>{room_name}</b>:",
        parse_mode="HTML"
    )


# --- Пользователь вводит запрос ---
@router.message(TrackAdd.waiting_for_query)
async def handle_track_query(message: types.Message, state: FSMContext):
    query = message.text.strip()  # type: ignore
    data = await state.get_data()
    room_id = data.get("room_id")

    # Отправляем сообщение о начале загрузки
    loading_msg = await message.answer(f"🔍 Ищу трек <b>{query}</b>...\n⏳ Это может занять некоторое время...", parse_mode="HTML")

    try:
        result = await download_track(query)
        if not result:
            await loading_msg.edit_text("⚠️ Не удалось найти или загрузить трек.")
            await state.clear()
            return

        # Получаем данные трека
        title = result["title"]
        audio_buf = result["buffer"]
        file_hash = result["hash"]
        print(f"🎯 title={title}, hash={file_hash}")

        # Проверка лимита Telegram (50 МБ)
        audio_buf.seek(0)
        if len(audio_buf.read()) > TG_MAX_FILE_BYTES:
            cache_path = CACHE_DIR / f"{file_hash}.mp3"
            meta_path = CACHE_DIR / f"{file_hash}.json"
            if cache_path.exists():
                cache_path.unlink()
            if meta_path.exists():
                meta_path.unlink()
            await loading_msg.edit_text(
                "⚠️ Файл превышает лимит Telegram (50 МБ). Трек не добавлен.",
                parse_mode="HTML"
            )
            await state.clear()
            return

        # Создаём временный ключ в redis
        token = secrets.token_hex(4)
        cache_key = f"pending_track:{token}"
        # Получаем имя пользователя: full_name или username
        user = message.from_user  # type: ignore
        added_by_name = user.full_name or (f"@{user.username}" if user.username else f"User {user.id}")
        
        track_data = {
            "room_id": room_id,
            "title": title,
            "file": file_hash,
            "user_id": user.id,
            "added_by": added_by_name
        }
        # Убираем ограничение времени - трек хранится без TTL (навсегда, пока не будет подтвержден)
        await redis_safe(redis.set(cache_key, json.dumps(track_data)))

        # Создаём кнопки подтверждения / отмены
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Добавить", callback_data=f"confirm:{token}:public")
        kb.button(text="🤫 Анонимно", callback_data=f"confirm:{token}:anon")
        kb.button(text="❌ Отмена", callback_data="cancel_add")
        kb.adjust(2)

        # Используем mp3 из памяти (важно: читаем buffer и создаем новый BytesIO)
        audio_buf.seek(0)  # Возвращаемся в начало буфера
        audio_data = audio_buf.read()
        input_file = types.BufferedInputFile(audio_data, filename=f"{title}.mp3")

        # Удаляем сообщение о загрузке и отправляем трек
        try:
            await loading_msg.delete()
        except Exception:
            pass

        await message.answer_audio(
            audio=input_file,
            caption=f"🎧 Это твой трек?",
            title=title,
            reply_markup=kb.as_markup()
        )

        await state.clear()
    except Exception as e:
        print(f"❌ Ошибка при загрузке трека: {e}")
        import traceback
        traceback.print_exc()
        try:
            await loading_msg.edit_text("⚠️ Произошла ошибка при загрузке трека. Попробуйте еще раз.")
        except Exception:
            await message.answer("⚠️ Произошла ошибка при загрузке трека. Попробуйте еще раз.")
        await state.clear()


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_track(callback: types.CallbackQuery):
    parts = callback.data.split(":")  # type: ignore
    token = parts[1]
    anon = len(parts) > 2 and parts[2] == "anon"
    cache_key = f"pending_track:{token}"

    data_raw = await redis_safe(redis.get(cache_key))
    if not data_raw:
        print(f"❌ Трек не найден в кэше: {cache_key}")
        
        # Проверяем, может быть трек уже был отправлен на модерацию
        # Ищем по user_track ключам для этого пользователя
        user_id = callback.from_user.id  # type: ignore
        try:
            # Ищем все user_track ключи для этого пользователя
            pattern = f"user_track:{user_id}:*"
            all_keys = []
            cursor = 0
            while True:
                cursor, keys = await redis_safe(redis.scan(cursor, match=pattern, count=100))
                all_keys.extend(keys)
                if cursor == 0:
                    break
            
            # Проверяем, есть ли трек с pending статусом
            for k in all_keys:
                key = k.decode() if isinstance(k, bytes) else str(k)
                track_data = await redis_safe(redis.get(key))
                if track_data:
                    try:
                        if isinstance(track_data, bytes):
                            track = json.loads(track_data.decode())
                        else:
                            track = json.loads(track_data) if isinstance(track_data, str) else track_data
                        
                        # Если трек уже на модерации, сообщаем об этом
                        if track.get("status") == "pending":
                            await callback.answer("⏳ Трек уже отправлен на модерацию. Ожидайте подтверждения администратора.", show_alert=True)
                            return
                    except:
                        pass
        except Exception as e:
            print(f"⚠️ Ошибка при проверке статуса трека: {e}")
        
        await callback.answer("⚠️ Истёк срок подтверждения трека. Пожалуйста, добавьте трек заново.", show_alert=True)
        return

    print(f"✅ Данные трека найдены в кэше: {cache_key}")
    try:
        data = json.loads(data_raw)
    except Exception as e:
        print(f"❌ Ошибка парсинга JSON: {e}, data_raw: {data_raw}")
        await callback.answer("⚠️ Ошибка обработки данных трека.", show_alert=True)
        return
    room_id = data["room_id"]
    title = data["title"]
    file_hash = data["file"]
    user_id = data["user_id"]
    added_by = "анонимно" if anon else data["added_by"]

    print(f"🧩 confirm_track: room_id={room_id}, title={title}, file_hash={file_hash}, user_id={user_id}, anon={anon}")

    # --- проверка лимита Telegram (50 МБ) ---
    cache_path = CACHE_DIR / f"{file_hash}.mp3"
    if cache_path.exists() and cache_path.stat().st_size > TG_MAX_FILE_BYTES:
        cache_path.unlink()
        meta_path = CACHE_DIR / f"{file_hash}.json"
        if meta_path.exists():
            meta_path.unlink()
        await callback.answer("⚠️ Файл превышает лимит Telegram (50 МБ). Трек не добавлен.", show_alert=True)
        return

    # --- проверяем, является ли пользователь админом/владельцем ---
    is_admin = await room_service.is_admin_or_owner(user_id, room_id)
    print(f"🔐 Пользователь {user_id} является админом/владельцем: {is_admin}")
    
    # --- проверяем модерацию (админы и владельцы пропускают модерацию) ---
    moderation_enabled = await room_service.is_moderation_enabled(room_id)
    print(f"🔐 Модерация включена: {moderation_enabled}")
    
    if moderation_enabled and not is_admin:
        # Отправляем на модерацию через сервис
        try:
            moderation_token = await moderation_service.submit_for_moderation(
                room_id=room_id,
                title=title,
                file_hash=file_hash,
                added_by=added_by,
                user_id=user_id,
                anon=anon
            )
            
            # Уведомляем админов
            await notification_service.notify_admins_new_moderation(
                room_id=room_id,
                track_title=title,
                added_by=added_by,
                exclude_user_id=user_id
            )
            
            await callback.answer("⏳ Трек отправлен на модерацию. Администраторы получат уведомление.")
            try:
                await callback.message.delete() # type: ignore
            except Exception:
                pass
            
            # Открываем комнату после отправки на модерацию
            total_tracks = len(await track_repo.get_all_tracks(room_id))
            per_page = 10
            last_page = max(0, (total_tracks - 1) // per_page)
            
            fake_callback = SimpleNamespace(
                data=f"roompage:{room_id}:{last_page}",
                from_user=callback.from_user,
                message=callback.message,
                bot=callback.bot
            )
            
            await open_room(fake_callback)
            return
        except Exception as e:
            print(f"❌ Ошибка при отправке на модерацию: {e}")
            await callback.answer("⚠️ Ошибка при отправке трека на модерацию.", show_alert=True)
            return
    
    # --- сохраняем трек напрямую (без модерации, админ добавляет) ---
    try:
        result = await track_service.add_track_to_room(
            room_id=room_id,
            title=title,
            file_hash=file_hash,
            added_by=added_by,
            user_id=user_id,
            anon=anon
        )
        
        print(f"✅ Трек {title} добавлен в комнату {room_id}")
        
        # Уведомляем участников
        await notification_service.notify_new_track(
            room_id=room_id,
            track_title=title,
            added_by=added_by,
            exclude_user_id=user_id
        )
        
        await callback.answer("✅ Трек добавлен!")
        try:
            await callback.message.delete()  # type: ignore
        except Exception:
            pass
        
        # Открываем комнату с обновленным списком треков
        total_tracks = len(await track_repo.get_all_tracks(room_id))
        per_page = 10
        last_page = max(0, (total_tracks - 1) // per_page)
        
        fake_callback = SimpleNamespace(
            data=f"roompage:{room_id}:{last_page}",
            from_user=callback.from_user,
            message=callback.message,
            bot=callback.bot
        )
        
        await open_room(fake_callback)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
    except Exception as e:
        print(f"❌ ОШИБКА при сохранении трека: {e}")
        import traceback
        traceback.print_exc()
        await callback.answer("⚠️ Ошибка при сохранении трека.", show_alert=True)


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


# --- Одобрение трека администратором (из уведомления) ---
@router.callback_query(F.data.startswith("approve_track:"))
async def approve_track(callback: types.CallbackQuery):
    """Одобряет трек из уведомления администратору"""
    parts = callback.data.split(":") # type: ignore
    room_id = parts[1]
    token = parts[2]
    admin_id = callback.from_user.id  # type: ignore
    
    # Проверяем права
    if not await room_service.is_admin_or_owner(admin_id, room_id):
        await callback.answer("❌ Только администраторы могут одобрять треки.", show_alert=True)
        return
    
    # Одобряем трек через сервис
    try:
        result = await moderation_service.approve_track(room_id, token, admin_id)
        title = result["track"]["title"]
        user_id = result["user_id"]
        added_by = result["track"].get("added_by", "Неизвестно")
        
        # Уведомляем пользователя через сервис
        await notification_service.notify_track_approved(user_id, room_id, title)
        
        # Уведомляем участников через сервис
        await notification_service.notify_new_track(
            room_id=room_id,
            track_title=title,
            added_by=added_by,
            exclude_user_id=user_id
        )
        
        await callback.answer("✅ Трек одобрен и добавлен!")
        
        # Удаляем сообщение с уведомлением о модерации
        try:
            await callback.message.delete() # type: ignore
        except Exception:
            pass
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
    except Exception as e:
        print(f"❌ Ошибка при одобрении трека: {e}")
        await callback.answer("⚠️ Ошибка при одобрении трека.", show_alert=True)


# --- Отклонение трека администратором ---
@router.callback_query(F.data.startswith("reject_track:"))
async def reject_track(callback: types.CallbackQuery):
    parts = callback.data.split(":") # type: ignore
    room_id = parts[1]
    token = parts[2]
    
    # Проверяем права
    admin_id = callback.from_user.id  # type: ignore
    if not await room_service.is_admin_or_owner(admin_id, room_id):
        await callback.answer("❌ Только администраторы могут отклонять треки.", show_alert=True)
        return
    
    # Отклоняем трек через сервис
    try:
        result = await moderation_service.reject_track(room_id, token, admin_id)
        title = result["track"]["title"]
        user_id = result["user_id"]
        
        # Уведомляем пользователя через сервис
        await notification_service.notify_track_rejected(user_id, room_id, title)
        
        await callback.answer("❌ Трек отклонен")
        try:
            await callback.message.delete() # type: ignore
        except Exception:
            pass
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
    except Exception as e:
        print(f"❌ Ошибка при отклонении трека: {e}")
        await callback.answer("⚠️ Ошибка при отклонении трека.", show_alert=True)


# --- Мои треки ---
@router.callback_query(F.data.startswith("my_tracks:"))
async def show_my_tracks(callback: types.CallbackQuery):
    parts = callback.data.split(":") # type: ignore
    room_id = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0
    user_id = callback.from_user.id # type: ignore
    
    # Получаем все треки пользователя через репозиторий
    tracks_data = await track_repo.get_user_tracks(user_id, room_id)
    
    if not tracks_data:
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Назад к комнате", callback_data=f"room:{room_id}")
        await callback.message.edit_text(  # type: ignore
            "🎵 <b>Мои треки</b>\n\n"
            "У вас пока нет треков в этой комнате.",
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
        return

    
    # Сортируем по статусу: pending, approved, rejected
    status_order = {"pending": 0, "approved": 1, "rejected": 2}
    tracks_data.sort(key=lambda x: (status_order.get(x.get("status", "approved"), 1), x.get("title", "")))
    
    # Подсчитываем статистику
    total_tracks = len(tracks_data)
    approved_count = len([t for t in tracks_data if t.get("status") == "approved"])
    
    # Пагинация
    per_page = 10
    total_pages = max(1, (total_tracks + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = start + per_page
    page_tracks = tracks_data[start:end]
    
    # Формируем текст
    text = f"🎵 <b>Мои треки</b>\n"
    
    # Показываем информацию о странице и статистику
    if total_pages > 1:
        text += f"📄 Страница {page + 1} из {total_pages}\n"
    text += f"✅ Добавлено: <b>{approved_count}</b> из <b>{total_tracks}</b> отправленных\n\n"
    
    status_emoji = {
        "pending": "⏳",
        "approved": "✅",
        "rejected": "❌"
    }
    status_text = {
        "pending": "На модерации",
        "approved": "Добавлен",
        "rejected": "Отклонен"
    }
    
    # Отображаем треки на текущей странице
    for track in page_tracks:
        status = track.get("status", "approved")
        emoji = status_emoji.get(status, "✅")
        status_label = status_text.get(status, "Добавлен")
        anon_label = " (🤫 анонимно)" if track.get("anon") else ""
        
        added_at = track.get("added_at")
        added_date = format_datetime(added_at) if added_at else "Неизвестно"
        
        text += f"{emoji} <b>{track.get('title', 'Неизвестно')}</b>{anon_label}\n"
        text += f"   📊 {status_label}\n"
        text += f"   📅 Добавлен: {added_date}\n"
        
        if status in ("approved", "rejected"):
            moderated_at = track.get("moderated_at")
            if moderated_at:
                moderated_date = format_datetime(moderated_at)
                action = "Одобрен" if status == "approved" else "Отклонен"
                text += f"   {emoji} {action}: {moderated_date}\n"
        text += "\n"
    
    # Клавиатура с пагинацией
    kb = InlineKeyboardBuilder()
    
    # Пагинация (если страниц больше 1)
    if total_pages > 1:
        nav_kb = build_my_tracks_page_nav(room_id, page, total_pages)
        for row in nav_kb.export():
            kb.row(*row)

    kb.button(text="📋 Список в чате", callback_data=f"my_tracks_list:{room_id}")
    kb.button(text="🔙 Назад к комнате", callback_data=f"room:{room_id}")
    
    await callback.message.edit_text( # type: ignore
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


# --- Список всех треков в чате (аудиофайлы) с кнопкой Назад ---
@router.callback_query(F.data.startswith("my_tracks_list:"))
async def show_my_tracks_list_in_chat(callback: types.CallbackQuery):
    """Отправляет все добавленные треки как аудиофайлы в чат, в конце — кнопка Назад"""
    room_id = callback.data.split(":")[1]  # type: ignore
    user_id = callback.from_user.id  # type: ignore

    all_tracks = await track_repo.get_user_tracks(user_id, room_id)
    tracks_data = [t for t in all_tracks if t.get("status") == "approved"]
    if not tracks_data:
        await callback.answer("Нет одобренных треков для воспроизведения.", show_alert=True)
        return

    tracks_data.sort(key=lambda x: x.get("title", ""))


    msg_ids = []
    chat_id = callback.message.chat.id  # type: ignore

    await callback.answer("⏳ Отправляю треки...")

    # Отправляем каждый трек как аудиофайл
    for i, track in enumerate(tracks_data, 1):
        file_hash = track.get("file")
        title = track.get("title", "Без названия")
        caption = f"🎵 {title} ({i}/{len(tracks_data)})"

        cache_path = CACHE_DIR / f"{file_hash}.mp3"
        if not cache_path.exists():
            continue

        try:
            audio_data = cache_path.read_bytes()
            input_file = types.BufferedInputFile(audio_data, filename=f"{title[:50]}.mp3")
            msg = await callback.bot.send_audio(  # type: ignore
                chat_id=chat_id,
                audio=input_file,
                title=title[:30] if title else None,
                caption=caption
            )
            msg_ids.append(msg.message_id)
        except Exception as e:
            print(f"❌ Ошибка отправки трека {title}: {e}")
            continue

    if not msg_ids:
        await callback.bot.send_message(chat_id, "⚠️ Не удалось отправить треки (файлы не найдены в кэше).")  # type: ignore
        return

    # Сообщение с кнопкой Назад
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад к комнате", callback_data=f"my_tracks_back:{room_id}")
    msg = await callback.bot.send_message(  # type: ignore
        chat_id,
        f"🎵 Отправлено {len(msg_ids)} треков из комнаты",
        reply_markup=kb.as_markup()
    )
    msg_ids.append(msg.message_id)

    # Сохраняем ID сообщений для удаления при нажатии Назад
    await redis_safe(redis.set(
        f"my_tracks_list_msgs:{user_id}:{room_id}",
        json.dumps(msg_ids),
        ex=3600
    ))


@router.callback_query(F.data.startswith("my_tracks_back:"))
async def my_tracks_back_to_room(callback: types.CallbackQuery):
    """Удаляет список треков из чата и возвращает в комнату"""
    room_id = callback.data.split(":")[1]  # type: ignore
    user_id = callback.from_user.id  # type: ignore
    chat_id = callback.message.chat.id  # type: ignore

    key = f"my_tracks_list_msgs:{user_id}:{room_id}"
    raw = await redis_safe(redis.get(key))
    if raw:
        try:
            msg_ids = json.loads(raw)
            for mid in msg_ids:
                try:
                    await callback.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
        except Exception:
            pass
        await redis_safe(redis.delete(key))

    fake_callback = SimpleNamespace(
        data=f"room:{room_id}",
        from_user=callback.from_user,
        message=callback.message,
        bot=callback.bot
    )
    await open_room(fake_callback)
    await callback.answer()


def build_my_tracks_page_nav(room_id: str, current_page: int, total_pages: int) -> InlineKeyboardBuilder:
    """Создает навигацию по страницам для 'Мои треки'"""
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
        kb.button(text="⬅️", callback_data=f"my_tracks:{room_id}:{current_page - 1}")

    # номера страниц
    for i in range(start, end):
        label = f"[{i+1}]" if i == current_page else str(i+1)
        kb.button(text=label, callback_data=f"my_tracks:{room_id}:{i}")

    # кнопка "вправо"
    if current_page < total_pages - 1 and total_pages > window:
        kb.button(text="➡️", callback_data=f"my_tracks:{room_id}:{current_page + 1}")

    # всё в одну строку
    kb.adjust(window + 2)
    return kb
