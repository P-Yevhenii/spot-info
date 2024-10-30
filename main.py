from aiogram import Bot, Dispatcher
from bot import BOT_TOKEN, router, scheduled_message
import asyncio

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


async def main():
    dp.include_router(router)

    await asyncio.create_task(scheduled_message(bot))

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
