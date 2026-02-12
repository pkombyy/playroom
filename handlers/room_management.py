"""
Handlers для управления комнатой: настройки, админы, блокировка пользователей
Рефакторинг с использованием Repository и Service слоев
"""
import json
from pathlib import Path
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import redis, bot as bot_instance
from utils.redis_helper import redis_safe
from handlers.rooms import open_room
from utils.youtube import CACHE_DIR
from utils.timezone import iso_now, now_tyumen, format_datetime
from types import SimpleNamespace
from services.room_service import RoomService
from services.moderation_service import ModerationService
from services.notification_service import NotificationService
from services.track_service import TrackService
from repositories.track_repository import TrackRepository
from repositories.moderation_repository import ModerationRepository
from repositories.room_repository import RoomRepository

# Инициализация сервисов и репозиториев
room_service = RoomService()
moderation_service = ModerationService()
notification_service = NotificationService()
track_service = TrackService()
track_repo = TrackRepository()
moderation_repo = ModerationRepository()
room_repo = RoomRepository()

router = Router()


class ManageUser(StatesGroup):
    waiting_for_user_id = State()


# --- Настройки комнаты ---
@router.callback_query(F.data.startswith("room_settings:"))
async def room_settings(callback: types.CallbackQuery):
    room_id = callback.data.split(":")[1] # type: ignore
    
    # Проверяем права
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Только администраторы могут изменять настройки.", show_alert=True)
        return
    
    moderation_enabled = await room_repo.is_moderation_enabled(room_id)
    moderation_status = "✅ Включена" if moderation_enabled else "❌ Выключена"
    
    # Проверяем количество треков на модерации через репозиторий
    pending_tracks = await moderation_repo.get_pending_tracks(room_id)
    queue_length = len(pending_tracks)
    
    kb = InlineKeyboardBuilder()
    kb.button(
        text=f"🔐 Модерация треков: {moderation_status}",
        callback_data=f"toggle_moderation:{room_id}"
    )
    if moderation_enabled and queue_length > 0:
        kb.button(
            text=f"📋 Очередь модерации ({queue_length})",
            callback_data=f"moderation_queue:{room_id}"
        )
    kb.button(text="👥 Управление пользователями", callback_data=f"manage_users:{room_id}")
    kb.button(text="👑 Администраторы", callback_data=f"manage_admins:{room_id}")
    kb.button(text="🚫 Заблокированные", callback_data=f"manage_banned:{room_id}")
    kb.button(text="🔙 Назад к комнате", callback_data=f"room:{room_id}")
    kb.adjust(1)
    
    queue_text = f"\n📋 Треков на модерации: {queue_length}" if moderation_enabled else ""
    
    await callback.message.edit_text( # type: ignore
        f"⚙️ <b>Настройки комнаты</b>\n\n"
        f"🔐 Модерация треков: {moderation_status}{queue_text}\n"
        f"При включенной модерации треки добавляются только после подтверждения администратором.",
        reply_markup=kb.as_markup()
    )


# --- Переключение модерации ---
@router.callback_query(F.data.startswith("toggle_moderation:"))
async def toggle_moderation(callback: types.CallbackQuery):
    room_id = callback.data.split(":")[1] # type: ignore
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    moderation_enabled = await room_repo.is_moderation_enabled(room_id)
    new_value = not moderation_enabled
    await room_repo.set_moderation(room_id, new_value)
    
    await callback.answer(f"✅ Модерация {'включена' if new_value else 'выключена'}")
    # Обновляем меню
    await room_settings(callback)


# --- Управление пользователями ---
@router.callback_query(F.data.startswith("manage_users:"))
async def manage_users(callback: types.CallbackQuery, state: FSMContext):
    room_id = callback.data.split(":")[1] # type: ignore
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    members = await room_repo.get_room_members(room_id)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить пользователя", callback_data=f"add_user:{room_id}")
    kb.button(text="🔙 Назад", callback_data=f"room_settings:{room_id}")
    kb.adjust(1)
    
    text = f"👥 <b>Участники комнаты</b>\n\nВсего: {len(members)}"
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup()) # type: ignore


# --- Добавление пользователя ---
@router.callback_query(F.data.startswith("add_user:"))
async def add_user_start(callback: types.CallbackQuery, state: FSMContext):
    room_id = callback.data.split(":")[1] # type: ignore
    await state.update_data(room_id=room_id)
    await state.set_state(ManageUser.waiting_for_user_id)
    
    await callback.message.edit_text( # type: ignore
        "📝 Введи ID пользователя для добавления в комнату:"
    )


# --- Управление администраторами ---
@router.callback_query(F.data.startswith("manage_admins:"))
async def manage_admins(callback: types.CallbackQuery):
    room_id = callback.data.split(":")[1] # type: ignore
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    owner_id = await room_repo.get_room_owner(room_id)
    admins = await room_repo.get_room_admins(room_id)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить администратора", callback_data=f"add_admin:{room_id}")
    
    # Список админов
    for admin_id in admins:
        if admin_id != owner_id:  # Не показываем владельца
            kb.button(
                text=f"👑 Админ {admin_id} (убрать)",
                callback_data=f"remove_admin:{room_id}:{admin_id}"
            )
    
    kb.button(text="🔙 Назад", callback_data=f"room_settings:{room_id}")
    kb.adjust(1)
    
    text = f"👑 <b>Администраторы комнаты</b>\n\n"
    if owner_id:
        text += f"👑 Владелец: {owner_id}\n"
    text += f"Администраторов: {len(admins)}"
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup()) # type: ignore


# --- Добавление администратора ---
@router.callback_query(F.data.startswith("add_admin:"))
async def add_admin_start(callback: types.CallbackQuery, state: FSMContext):
    room_id = callback.data.split(":")[1] # type: ignore
    await state.update_data(room_id=room_id, action="add_admin")
    await state.set_state(ManageUser.waiting_for_user_id)
    
    await callback.message.edit_text( # type: ignore
        "📝 Введи ID пользователя для назначения администратором:"
    )


# --- Удаление администратора ---
@router.callback_query(F.data.startswith("remove_admin:"))
async def remove_admin(callback: types.CallbackQuery):
    parts = callback.data.split(":") # type: ignore
    room_id = parts[1]
    admin_id = int(parts[2])
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Нельзя убрать владельца
    owner_id = await room_repo.get_room_owner(room_id)
    if admin_id == owner_id:
        await callback.answer("❌ Нельзя убрать владельца.", show_alert=True)
        return
    
    await room_repo.remove_room_admin(room_id, admin_id)
    await callback.answer("✅ Администратор убран.")
    await manage_admins(callback)


# --- Управление заблокированными ---
@router.callback_query(F.data.startswith("manage_banned:"))
async def manage_banned(callback: types.CallbackQuery):
    room_id = callback.data.split(":")[1] # type: ignore
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    banned = await room_repo.get_room_banned(room_id)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Заблокировать пользователя", callback_data=f"ban_user:{room_id}")
    
    for banned_id in banned:
        kb.button(
            text=f"🚫 {banned_id} (разблокировать)",
            callback_data=f"unban_user:{room_id}:{banned_id}"
        )
    
    kb.button(text="🔙 Назад", callback_data=f"room_settings:{room_id}")
    kb.adjust(1)
    
    text = f"🚫 <b>Заблокированные пользователи</b>\n\nВсего: {len(banned)}"
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup()) # type: ignore


# --- Блокировка пользователя ---
@router.callback_query(F.data.startswith("ban_user:"))
async def ban_user_start(callback: types.CallbackQuery, state: FSMContext):
    room_id = callback.data.split(":")[1] # type: ignore
    await state.update_data(room_id=room_id, action="ban")
    await state.set_state(ManageUser.waiting_for_user_id)
    
    await callback.message.edit_text( # type: ignore
        "📝 Введи ID пользователя для блокировки:"
    )


# --- Разблокировка пользователя ---
@router.callback_query(F.data.startswith("unban_user:"))
async def unban_user(callback: types.CallbackQuery):
    parts = callback.data.split(":") # type: ignore
    room_id = parts[1]
    user_id = int(parts[2])
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    await room_repo.unban_user(room_id, user_id)
    await callback.answer("✅ Пользователь разблокирован.")
    await manage_banned(callback)


# Обработка действий с пользователями через сообщение
@router.message(ManageUser.waiting_for_user_id)
async def handle_user_action(message: types.Message, state: FSMContext):
    data = await state.get_data()
    room_id = data.get("room_id")
    action = data.get("action")
    
    try:
        user_id = int(message.text.strip()) # type: ignore
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введи число.")
        return
    
    if action == "add_admin":
        await room_repo.add_room_admin(room_id, user_id)
        await message.answer(f"✅ Пользователь {user_id} назначен администратором.")
    elif action == "ban":
        await room_repo.ban_user(room_id, user_id)
        await message.answer(f"✅ Пользователь {user_id} заблокирован.")
    else:
        # По умолчанию добавляем как участника
        role = await room_service.get_user_role(user_id, room_id)
        if role == "banned":
            await message.answer("❌ Этот пользователь заблокирован. Сначала разблокируйте его.")
        else:
            await room_repo.add_room_member(room_id, user_id)
            await message.answer(f"✅ Пользователь {user_id} добавлен в комнату.")
    
    await state.clear()


# --- Очередь модерации ---
@router.callback_query(F.data.startswith("moderation_queue:"))
async def show_moderation_queue(callback: types.CallbackQuery):
    """Показывает очередь модерации с первым треком для модерирования"""
    room_id = callback.data.split(":")[1] # type: ignore
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Получаем pending треки через репозиторий (автоматически возвращает в pending при неактивности)
    # Сначала принудительно восстанавливаем все потерянные треки
    restored = await moderation_repo.restore_all_pending_from_user_tracks(room_id)
    if restored > 0:
        print(f"✅ Восстановлено {restored} потерянных треков для комнаты {room_id}")
    
    pending_tracks = await moderation_repo.get_pending_tracks(room_id)
    
    if not pending_tracks:
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отклоненные треки", callback_data=f"rejected_tracks:{room_id}")
        kb.button(text="🔙 Назад к комнате", callback_data=f"room:{room_id}")
        kb.adjust(1)
        await callback.message.edit_text( # type: ignore
            "📋 <b>Очередь модерации</b>\n\n"
            "✅ Нет треков на модерации.",
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
        return
    
    # Показываем первый трек для модерации
    first_track = pending_tracks[0]
    token = first_track.get("token")
    
    text = f"📋 <b>Очередь модерации</b>\n\n"
    text += f"🎵 <b>{first_track.get('title', 'Неизвестно')}</b>\n"
    text += f"👤 От: {first_track.get('added_by', 'Неизвестно')}\n"
    text += f"📊 В очереди: <b>{len(pending_tracks)}</b> треков\n"
    
    kb = InlineKeyboardBuilder()
    
    # Кнопка прослушать
    if first_track.get("file"):
        kb.button(text="🎧 Прослушать", callback_data=f"mod_play_track:{room_id}:{token}")
    
    # Кнопки модерации
    kb.button(text="✅ Добавить", callback_data=f"mod_approve:{room_id}:{token}")
    kb.button(text="❌ Отклонить", callback_data=f"mod_reject:{room_id}:{token}")
    kb.adjust(2)
    
    # Кнопка отклоненных треков (всегда доступна)
    kb.button(text="❌ Отклоненные треки", callback_data=f"rejected_tracks:{room_id}")
    
    # Кнопка возврата к комнате
    kb.button(text="🔙 Назад к комнате", callback_data=f"room:{room_id}")
    kb.adjust(1)
    
    await callback.message.edit_text( # type: ignore
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


# --- Прослушивание трека в модерации ---
@router.callback_query(F.data.startswith("mod_play_track:"))
async def mod_play_track(callback: types.CallbackQuery):
    """Отправляет трек для прослушивания в процессе модерации"""
    parts = callback.data.split(":")  # type: ignore
    room_id = parts[1]
    token = parts[2]
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Получаем данные трека через репозиторий
    data = await moderation_repo.get_moderation_track(room_id, token)
    if not data:
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return
    
    file_hash = data.get("file")
    title = data.get("title", "Трек")
    
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


# --- Одобрение трека в модерации ---
@router.callback_query(F.data.startswith("mod_approve:"))
async def mod_approve_track(callback: types.CallbackQuery):
    """Одобряет трек из модерации"""
    parts = callback.data.split(":")  # type: ignore
    room_id = parts[1]
    token = parts[2]
    admin_id = callback.from_user.id  # type: ignore
    
    if not await room_service.is_admin_or_owner(admin_id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Одобряем трек через сервис
    try:
        result = await moderation_service.approve_track(room_id, token, admin_id)
        title = result["track"]["title"]
        user_id = result["user_id"]
        already_exists = result.get("already_exists", False)
        
        if already_exists:
            # Трек уже был в плейлисте - просто удалили дубликат из модерации
            await callback.answer("✅ Дубликат удален из модерации. Трек уже в плейлисте.")
        else:
            # Уведомляем пользователя через сервис
            await notification_service.notify_track_approved(user_id, room_id, title)
            await callback.answer("✅ Трек одобрен и добавлен в плейлист")
        
        # Переходим к следующему треку в модерации
        await show_moderation_queue(callback)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
    except Exception as e:
        print(f"❌ Ошибка при одобрении трека: {e}")
        await callback.answer("⚠️ Ошибка при одобрении трека.", show_alert=True)


# --- Отклонение трека в модерации ---
@router.callback_query(F.data.startswith("mod_reject:"))
async def mod_reject_track(callback: types.CallbackQuery):
    """Отклоняет трек из модерации"""
    parts = callback.data.split(":")  # type: ignore
    room_id = parts[1]
    token = parts[2]
    admin_id = callback.from_user.id  # type: ignore
    
    if not await room_service.is_admin_or_owner(admin_id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Отклоняем трек через сервис
    try:
        result = await moderation_service.reject_track(room_id, token, admin_id)
        title = result["track"]["title"]
        user_id = result["user_id"]
        
        # Уведомляем пользователя через сервис
        await notification_service.notify_track_rejected(user_id, room_id, title)
        
        await callback.answer("❌ Трек отклонен")
        
        # Переходим к следующему треку в модерации
        await show_moderation_queue(callback)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
    except Exception as e:
        print(f"❌ Ошибка при отклонении трека: {e}")
        await callback.answer("⚠️ Ошибка при отклонении трека.", show_alert=True)


# --- Просмотр отклоненных треков ---
@router.callback_query(F.data.startswith("rejected_tracks:"))
async def show_rejected_tracks(callback: types.CallbackQuery):
    """Показывает список отклоненных треков"""
    room_id = callback.data.split(":")[1]  # type: ignore
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Получаем отклоненные треки через репозиторий
    tracks_data = await moderation_repo.get_rejected_tracks(room_id)
    
    if not tracks_data:
        kb = InlineKeyboardBuilder()
        kb.button(text="📋 Очередь модерации", callback_data=f"moderation_queue:{room_id}")
        kb.button(text="🔙 Назад к комнате", callback_data=f"room:{room_id}")
        kb.adjust(1)
        await callback.message.edit_text( # type: ignore
            "❌ <b>Отклоненные треки</b>\n\n"
            "Нет отклоненных треков.",
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
        return
    
    # Формируем список
    text = f"❌ <b>Отклоненные треки</b>\n\n"
    text += f"Всего: {len(tracks_data)}\n\n"
    
    kb = InlineKeyboardBuilder()
    
    # Показываем первые 10 треков
    for i, track in enumerate(tracks_data[:10], 1):
        text += f"{i}. <b>{track['title']}</b>\n"
        text += f"   👤 От: {track['added_by']}\n\n"
        
        kb.button(
            text=f"🎵 {track['title'][:30]}...",
            callback_data=f"view_rejected:{room_id}:{track['token']}"
        )
    
    if len(tracks_data) > 10:
        text += f"\n... и еще {len(tracks_data) - 10} треков"
    
    kb.button(text="📋 Очередь модерации", callback_data=f"moderation_queue:{room_id}")
    kb.button(text="🔙 Назад к комнате", callback_data=f"room:{room_id}")
    kb.adjust(1)
    
    await callback.message.edit_text( # type: ignore
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


# --- Просмотр отклоненного трека ---
@router.callback_query(F.data.startswith("view_rejected:"))
async def view_rejected_track(callback: types.CallbackQuery):
    """Показывает информацию об отклоненном треке с возможностью добавить в плейлист"""
    parts = callback.data.split(":")  # type: ignore
    room_id = parts[1]
    token = parts[2]
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Получаем данные трека
    rejected_key = f"rejected_tracks:{room_id}:{token}"
    data_raw = await redis_safe(redis.get(rejected_key))
    if not data_raw:
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return
    
    data = json.loads(data_raw)
    title = data.get("title", "Неизвестно")
    added_by = data.get("added_by", "Неизвестно")
    file_hash = data.get("file")
    added_at = data.get("added_at")
    moderated_at = data.get("moderated_at")
    
    # Форматируем даты через timezone утилиту
    added_date = format_datetime(added_at)
    moderated_date = format_datetime(moderated_at) if moderated_at else "Неизвестно"
    
    text = f"❌ <b>Отклоненный трек</b>\n\n"
    text += f"🎵 <b>{title}</b>\n"
    text += f"👤 Добавил: <b>{added_by}</b>\n"
    text += f"📅 Дата добавления: <b>{added_date}</b>\n"
    text += f"📅 Дата отклонения: <b>{moderated_date}</b>\n"
    
    kb = InlineKeyboardBuilder()
    
    # Кнопка прослушать
    if file_hash:
        audio_file = CACHE_DIR / f"{file_hash}.mp3"
        if audio_file.exists():
            kb.button(text="🎧 Прослушать", callback_data=f"rej_play_track:{room_id}:{token}")
    
    # Кнопка добавить в плейлист
    kb.button(text="✅ Добавить в плейлист", callback_data=f"restore_rejected:{room_id}:{token}")
    
    # Кнопка назад к списку отклоненных
    kb.button(text="🔙 Назад к отклоненным", callback_data=f"rejected_tracks:{room_id}")
    
    kb.adjust(1)
    
    await callback.message.edit_text( # type: ignore
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


# --- Прослушивание отклоненного трека ---
@router.callback_query(F.data.startswith("rej_play_track:"))
async def rej_play_track(callback: types.CallbackQuery):
    """Отправляет отклоненный трек для прослушивания"""
    parts = callback.data.split(":")  # type: ignore
    room_id = parts[1]
    token = parts[2]
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Получаем данные трека через репозиторий
    data = await moderation_repo.get_rejected_track(room_id, token)
    if not data:
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return
    
    file_hash = data.get("file")
    title = data.get("title", "Трек")
    
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


# --- Восстановление отклоненного трека в плейлист ---
@router.callback_query(F.data.startswith("restore_rejected:"))
async def restore_rejected_track(callback: types.CallbackQuery):
    """Добавляет отклоненный трек обратно в плейлист"""
    parts = callback.data.split(":")  # type: ignore
    room_id = parts[1]
    token = parts[2]
    admin_id = callback.from_user.id  # type: ignore
    
    if not await room_service.is_admin_or_owner(admin_id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Восстанавливаем трек через сервис
    try:
        result = await moderation_service.restore_rejected_track(room_id, token)
        title = result["track"]["title"]
        user_id = result["user_id"]
        
        # Уведомляем пользователя через сервис
        await notification_service.notify_track_restored(user_id, room_id, title)
        
        await callback.answer("✅ Трек добавлен в плейлист")
        
        # Возвращаемся к списку отклоненных с обновленными данными
        await show_rejected_tracks(callback)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
    except Exception as e:
        print(f"❌ Ошибка при восстановлении трека: {e}")
        await callback.answer("⚠️ Ошибка при восстановлении трека.", show_alert=True)


# --- Управление статусами треков пользователей (для админов) ---
@router.callback_query(F.data.startswith("manage_user_tracks:"))
async def manage_user_tracks(callback: types.CallbackQuery):
    parts = callback.data.split(":") # type: ignore
    room_id = parts[1]
    target_user_id = int(parts[2]) if len(parts) > 2 else None
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    if not target_user_id:
        # Показываем список пользователей с треками
        # Это можно реализовать позже, пока просто возвращаемся
        await callback.answer("⚠️ Функция в разработке", show_alert=True)
        return
    
    # Получаем треки пользователя
    track_tokens_raw = await redis_safe(redis.smembers(f"user:{target_user_id}:tracks:{room_id}"))
    track_tokens = [
        t.decode() if isinstance(t, bytes) else str(t)
        for t in (track_tokens_raw or [])
    ]
    
    if not track_tokens:
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Назад", callback_data=f"room_settings:{room_id}")
        await callback.message.edit_text( # type: ignore
            f"🎵 <b>Треки пользователя {target_user_id}</b>\n\n"
            "У пользователя нет треков в этой комнате.",
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
        return
    
    # Получаем данные о треках
    tracks_data = []
    for token in track_tokens:
        user_track_key = f"user_track:{target_user_id}:{room_id}:{token}"
        data_raw = await redis_safe(redis.get(user_track_key))
        if data_raw:
            try:
                data = json.loads(data_raw)
                tracks_data.append(data)
            except Exception:
                pass
    
    # Группируем по статусам
    approved_tracks = [t for t in tracks_data if t.get("status") == "approved"]
    rejected_tracks = [t for t in tracks_data if t.get("status") == "rejected"]
    
    text = f"🎵 <b>Управление треками пользователя {target_user_id}</b>\n\n"
    
    kb = InlineKeyboardBuilder()
    
    # Показываем отклоненные треки с возможностью вернуть в очередь
    if rejected_tracks:
        text += f"❌ <b>Отклоненные ({len(rejected_tracks)})</b>\n"
        for track in rejected_tracks[:5]:  # Показываем первые 5
            text += f"  • {track.get('title', 'Неизвестно')}\n"
            kb.button(
                text=f"↩️ Вернуть в очередь: {track.get('title', '')[:25]}...",
                callback_data=f"restore_track:{room_id}:{target_user_id}:{track.get('token')}"
            )
        kb.adjust(1)
        text += "\n"
    
    # Показываем одобренные треки с возможностью отклонить
    if approved_tracks:
        text += f"✅ <b>Одобренные ({len(approved_tracks)})</b>\n"
        for track in approved_tracks[:5]:  # Показываем первые 5
            text += f"  • {track.get('title', 'Неизвестно')}\n"
            kb.button(
                text=f"❌ Отклонить: {track.get('title', '')[:25]}...",
                callback_data=f"reject_approved:{room_id}:{target_user_id}:{track.get('token')}"
            )
        kb.adjust(1)
        text += "\n"
    
    kb.button(text="🔙 Назад", callback_data=f"room_settings:{room_id}")
    kb.adjust(1)
    
    await callback.message.edit_text( # type: ignore
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


# --- Восстановление трека из отклоненных в очередь модерации ---
@router.callback_query(F.data.startswith("restore_track:"))
async def restore_track(callback: types.CallbackQuery):
    parts = callback.data.split(":") # type: ignore
    room_id = parts[1]
    user_id = int(parts[2])
    token = parts[3]
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Получаем данные трека
    user_track_key = f"user_track:{user_id}:{room_id}:{token}"
    data_raw = await redis_safe(redis.get(user_track_key))
    
    if not data_raw:
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return
    
    track_data = json.loads(data_raw)
    
    # Возвращаем в очередь модерации
    moderation_key = f"moderation_queue:{room_id}:{token}"
    moderation_data = {
        "title": track_data.get("title"),
        "file": track_data.get("file"),
        "added_by": track_data.get("added_by"),
        "user_id": user_id,
        "token": token,
        "status": "pending",
        "anon": track_data.get("anon", False)
    }
    await redis_safe(redis.set(moderation_key, json.dumps(moderation_data), ex=86400))
    await redis_safe(redis.rpush(f"room:{room_id}:moderation_queue", token))
    
    # Обновляем статус трека пользователя
    track_data["status"] = "pending"
    await redis_safe(redis.set(user_track_key, json.dumps(track_data), ex=604800))
    
    # Уведомляем пользователя
    try:
        from config import bot as bot_instance
        await bot_instance.send_message(
            user_id,
            f"🔄 Трек <b>{track_data.get('title')}</b> возвращен в очередь модерации в комнате <b>{room_id}</b>.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    
    await callback.answer("✅ Трек возвращен в очередь модерации")
    await manage_user_tracks(callback)


# --- Отклонение одобренного трека ---
@router.callback_query(F.data.startswith("reject_approved:"))
async def reject_approved_track(callback: types.CallbackQuery):
    parts = callback.data.split(":") # type: ignore
    room_id = parts[1]
    user_id = int(parts[2])
    token = parts[3]
    
    if not await room_service.is_admin_or_owner(callback.from_user.id, room_id):  # type: ignore
        await callback.answer("❌ Нет прав.", show_alert=True)
        return
    
    # Получаем данные трека
    user_track_key = f"user_track:{user_id}:{room_id}:{token}"
    data_raw = await redis_safe(redis.get(user_track_key))
    
    if not data_raw:
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return
    
    track_data = json.loads(data_raw)
    title = track_data.get("title")
    file_hash = track_data.get("file")
    
    # Удаляем трек из плейлиста комнаты
    tracks_raw = await redis_safe(redis.lrange(f"room:{room_id}:tracks", 0, -1))
    for i, t_raw in enumerate(tracks_raw or []):
        try:
            t = json.loads(t_raw)
            if t.get("file") == file_hash or t.get("title", "").lower() == title.lower():
                await redis_safe(redis.lset(f"room:{room_id}:tracks", i, "__deleted__"))
                await redis_safe(redis.lrem(f"room:{room_id}:tracks", 1, "__deleted__"))
                break
        except Exception:
            pass
    
    # Обновляем статус трека пользователя
    track_data["status"] = "rejected"
    await redis_safe(redis.set(user_track_key, json.dumps(track_data), ex=604800))
    
    # Уведомляем пользователя
    try:
        from config import bot as bot_instance
        name_raw = await redis_safe(redis.get(f"room:{room_id}:name"))
        room_name = name_raw.decode() if isinstance(name_raw, bytes) else str(name_raw or room_id)
        await bot_instance.send_message(
            user_id,
            f"❌ Трек <b>{title}</b> отклонен администратором в комнате <b>{room_name}</b>.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    
    await callback.answer("✅ Трек отклонен и удален из плейлиста")
    await manage_user_tracks(callback)
