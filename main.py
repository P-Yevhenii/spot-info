from aiogram import Dispatcher
from bot import router, bot, scheduled_message
import asyncio

dp = Dispatcher()


async def main():
    dp.include_router(router)
    task = None
    try:
        task = asyncio.create_task(scheduled_message())
        await dp.start_polling(bot)
        await task
    finally:
        task.cancel()
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
