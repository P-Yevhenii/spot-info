import asyncio
import logging

from aiogram import Dispatcher

from bot import bot, router, scheduled_message

dp = Dispatcher()


async def main():
    dp.include_router(router)
    scheduled_task = asyncio.create_task(scheduled_message())
    try:
        await dp.start_polling(bot)
    finally:
        scheduled_task.cancel()
        await asyncio.gather(scheduled_task, return_exceptions=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
