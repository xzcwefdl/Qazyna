"""Главный файл бота QazynaDelivery"""
import asyncio
import logging
import signal
import sys
from logging.handlers import TimedRotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database import init_db, close_db
from handlers import router

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        TimedRotatingFileHandler("bot.log", when="midnight", interval=1, backupCount=7, encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# Graceful shutdown
shutdown_event = asyncio.Event()


def signal_handler(sig, frame):
    """Обработка SIGTERM/SIGINT"""
    logger.info(f"Получен сигнал {sig}, завершаем работу...")
    shutdown_event.set()


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


async def main():
    """Главная функция запуска бота"""
    await init_db()
    logger.info("База данных инициализирована")

    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)

    logger.info("Бот запущен!")

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка в polling: {e}")
    finally:
        await close_db()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Прервано пользователем")