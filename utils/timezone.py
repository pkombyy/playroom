"""
Утилита для работы с временем в часовом поясе Тюмени (UTC+5)
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

# Часовой пояс Тюмени (UTC+5)
TYUMEN_TZ = timezone(timedelta(hours=5))


def now_tyumen() -> datetime:
    """Возвращает текущее время в часовом поясе Тюмени"""
    return datetime.now(TYUMEN_TZ)


def to_tyumen(dt: datetime) -> datetime:
    """Конвертирует datetime в часовой пояс Тюмени"""
    if dt.tzinfo is None:
        # Если время без часового пояса, считаем его UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TYUMEN_TZ)


def format_datetime(dt: Optional[datetime | str], format_str: str = "%d.%m.%Y %H:%M") -> str:
    """
    Форматирует datetime в строку
    
    Args:
        dt: datetime объект или ISO строка
        format_str: формат для strftime
    
    Returns:
        Отформатированная строка или "Неизвестно" если dt None
    """
    if dt is None:
        return "Неизвестно"
    
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return dt
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    dt_tyumen = to_tyumen(dt)
    return dt_tyumen.strftime(format_str)


def iso_now() -> str:
    """Возвращает текущее время в ISO формате в часовом поясе Тюмени"""
    return now_tyumen().isoformat()


def parse_iso(iso_str: str) -> datetime:
    """Парсит ISO строку и возвращает datetime в часовом поясе Тюмени"""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return to_tyumen(dt)
