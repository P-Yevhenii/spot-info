import asyncio
from datetime import datetime, time

from aiogram import Bot, types
from aiogram import Router
from aiogram.filters import Command
from dotenv import load_dotenv
import os
import ccxt

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
BYBIT_API_KEY = os.getenv('BYBIT_API_KEY')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET')

router = Router()

TG_USERS = ["454078708", "482953524"]

client = ccxt.bybit({"api_key": BYBIT_API_KEY, "api_secret": BYBIT_API_SECRET})

target_time = time(hour=3, minute=0, second=0)


def get_spot_data(symbol="USDT/EUR"):
    try:
        ticker = client.fetch_ticker(symbol)
        price = ticker['last']
        return price
    except Exception as e:
        print(f"Error fetching spot data: {e}")  # TODO: write logs


@router.message(Command('start'))
async def start(message: types.Message):
    await message.answer(text="<b>The Bot for everyday EUR/USDT price!\n</b>", parse_mode="HTML")


async def scheduled_message(bot: Bot):
    while True:
        now = datetime.now().time()
        if now >= target_time and now.hour == target_time.hour and now.minute == target_time.minute:
            price = get_spot_data()
            daily_message = f"Market: <b>Spot</b>\nPair: <b>EUR/USDT</b>\nPrice: <b>{price}</b>\n"
            for user in TG_USERS:
                try:
                    await bot.send_message(user, daily_message, parse_mode="HTML")
                except Exception as e:
                    print(f"User not start his chat with bot: {e}")  # write logs
            await asyncio.sleep(60)
        await asyncio.sleep(1)

