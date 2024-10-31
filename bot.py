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

bot = Bot(token=BOT_TOKEN)

router = Router()

TG_USERS = ["454078708", "482953524"]

client = ccxt.bybit({"api_key": BYBIT_API_KEY, "api_secret": BYBIT_API_SECRET})

target_start = time(hour=7, minute=0, second=0)
target_end = time(hour=23, minute=0, second=0)


def get_spot_data(symbol="USDT/EUR"):
    try:
        ticker = client.fetch_ticker(symbol)
        price = ticker['last']
        return price
    except Exception as e:
        print(f"Error fetching spot data: {e}")  # TODO: write logs


async def scheduled_message():
    while True:
        now = datetime.now().time()
        if target_start <= now <= target_end:
            price = get_spot_data()
            daily_message = f"Market: <b>Spot</b>\nPair: <b>EUR/USDT</b>\nPrice: <b>{price}</b>\n"
            for user in TG_USERS:
                try:
                    await bot.send_message(user, daily_message, parse_mode="HTML")
                except Exception as e:
                    print(f"User not start his chat with bot: {e}")  # write logs
            await asyncio.sleep(3600)
        await asyncio.sleep(1)


@router.message(Command('start'))
async def start(message: types.Message):
    await message.answer(text="<b>Welcome to the Bot for everyday EUR/USDT price!\n</b>", parse_mode="HTML")








