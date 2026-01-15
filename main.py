import asyncio
import logging
from config import bot, dp
from handlers.tracks import router as tracks_router
from handlers.rooms import router as rooms_router
from handlers.rooms_create import router as create_router
from handlers.start import router as start_router
from handlers.room_management import router as management_router
logging.basicConfig(level=logging.INFO)

async def main():
    try:
        dp.include_router(start_router)
        dp.include_router(rooms_router)
        dp.include_router(create_router)
        dp.include_router(tracks_router)
        dp.include_router(management_router)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())