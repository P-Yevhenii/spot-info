from aiogram import Dispatcher
from bot import router, bot, scheduled_message
import asyncio

dp = Dispatcher()


async def main():
    dp.include_router(router)
    try:
        await asyncio.gather(
            dp.start_polling(bot),
            scheduled_message())

    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
