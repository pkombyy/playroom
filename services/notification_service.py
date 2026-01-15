"""
Service для отправки уведомлений
"""
from typing import List, Optional
from config import bot as bot_instance
from repositories.room_repository import RoomRepository
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    """Сервис для отправки уведомлений"""
    
    def __init__(self):
        self.room_repo = RoomRepository()
    
    async def notify_track_approved(self, user_id: int, room_id: str, track_title: str) -> bool:
        """Уведомляет пользователя об одобрении трека"""
        try:
            room_name = await self.room_repo.get_room_name(room_id) or room_id
            message = (
                f"✅ Трек <b>{track_title}</b> одобрен администратором "
                f"в комнате <b>{room_name}</b>."
            )
            await bot_instance.send_message(user_id, message, parse_mode="HTML")
            logger.info(f"✅ Уведомление об одобрении отправлено пользователю {user_id}")
            return True
        except Exception as e:
            logger.error(f"⚠️ Не удалось отправить уведомление пользователю {user_id}: {e}")
            return False
    
    async def notify_track_rejected(self, user_id: int, room_id: str, track_title: str) -> bool:
        """Уведомляет пользователя об отклонении трека"""
        try:
            room_name = await self.room_repo.get_room_name(room_id) or room_id
            message = (
                f"❌ Трек <b>{track_title}</b> отклонен администратором "
                f"в комнате <b>{room_name}</b>."
            )
            await bot_instance.send_message(user_id, message, parse_mode="HTML")
            logger.info(f"✅ Уведомление об отклонении отправлено пользователю {user_id}")
            return True
        except Exception as e:
            logger.error(f"⚠️ Не удалось отправить уведомление пользователю {user_id}: {e}")
            return False
    
    async def notify_track_restored(self, user_id: int, room_id: str, track_title: str) -> bool:
        """Уведомляет пользователя о восстановлении трека"""
        try:
            room_name = await self.room_repo.get_room_name(room_id) or room_id
            message = (
                f"✅ Трек <b>{track_title}</b> добавлен в плейлист администратором "
                f"в комнате <b>{room_name}</b>."
            )
            await bot_instance.send_message(user_id, message, parse_mode="HTML")
            logger.info(f"✅ Уведомление о восстановлении отправлено пользователю {user_id}")
            return True
        except Exception as e:
            logger.error(f"⚠️ Не удалось отправить уведомление пользователю {user_id}: {e}")
            return False
    
    async def notify_new_track(
        self,
        room_id: str,
        track_title: str,
        added_by: str,
        exclude_user_id: Optional[int] = None
    ) -> int:
        """Уведомляет участников комнаты о новом треке"""
        members = await self.room_repo.get_room_members(room_id)
        owner = await self.room_repo.get_room_owner(room_id)
        
        if owner and owner not in members:
            members.append(owner)
        
        room_name = await self.room_repo.get_room_name(room_id) or room_id
        message = (
            f"🎵 В комнату <b>{room_name}</b> добавлен новый трек:\n"
            f"<b>{track_title}</b> от {added_by}"
        )
        
        sent_count = 0
        for member_id in members:
            if member_id != exclude_user_id:
                try:
                    await bot_instance.send_message(member_id, message, parse_mode="HTML")
                    sent_count += 1
                except Exception as e:
                    logger.error(f"⚠️ Не удалось отправить уведомление участнику {member_id}: {e}")
        
        logger.info(f"📨 Отправлено уведомлений о новом треке: {sent_count}/{len(members)}")
        return sent_count
    
    async def notify_admins_new_moderation(
        self,
        room_id: str,
        track_title: str,
        added_by: str,
        exclude_user_id: Optional[int] = None
    ) -> int:
        """Уведомляет админов о новом треке на модерацию"""
        admins = await self.room_repo.get_room_admins(room_id)
        owner = await self.room_repo.get_room_owner(room_id)
        
        if owner and owner not in admins:
            admins.append(owner)
        
        room_name = await self.room_repo.get_room_name(room_id) or room_id
        message = (
            f"🔔 <b>Новый трек на модерацию</b>\n\n"
            f"🎵 <b>{track_title}</b>\n"
            f"👤 От: {added_by}\n"
            f"🏠 Комната: <b>{room_name}</b>"
        )
        
        sent_count = 0
        for admin_id in admins:
            if admin_id != exclude_user_id:
                try:
                    await bot_instance.send_message(admin_id, message, parse_mode="HTML")
                    sent_count += 1
                except Exception as e:
                    logger.error(f"⚠️ Не удалось отправить уведомление админу {admin_id}: {e}")
        
        logger.info(f"📨 Отправлено уведомлений админам: {sent_count}/{len(admins)}")
        return sent_count
