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

target_start = time(hour=6, minute=0, second=0)
target_end = time(hour=23, minute=0, second=0)


def get_spot_data(symbol="USDT/EUR"):
    try:
        ticker = client.fetch_ticker(symbol)
        price = ticker['last']
        return price
    except Exception as e:
        print(f"Error fetching spot data: {e}")


def get_trend(current, previous):
    if current > previous:
        return "⬆️"
    elif current < previous:
        return "⬇️"
    else:
        return "➡️"


async def scheduled_message():
    price_usdt = get_spot_data()
    price_usdc = get_spot_data("USDC/EUR")
    prev_price_usdt = price_usdt
    prev_price_usdc = price_usdc

    while True:
        now = datetime.now().time()
        if target_start <= now <= target_end:
            daily_message = "<b>📊 Market spot: ByBit</b>\n\n<pre>"
            daily_message += f"{'Pair':<12} {'Price':>10} {'Trend':>5}\n"
            daily_message += "-" * 30 + "\n"
            daily_message += f"🇪🇺/💲 EUR/USDT  {str(price_usdt):>10}  {get_trend(price_usdt, prev_price_usdt):>5}\n"
            daily_message += f"🇪🇺/💵 EUR/USDC  {str(price_usdc):>10}  {get_trend(price_usdc, prev_price_usdc):>5}\n"
            daily_message += "</pre>"

            for user in TG_USERS:
                try:
                    await bot.send_message(user, daily_message, parse_mode="HTML")
                except Exception as e:
                    print(f"User not start his chat with bot: {e}")

            await bot.send_message(
                chat_id="-1002905214084",
                message_thread_id=203,
                text=daily_message,
                parse_mode="HTML",
            )
            await asyncio.sleep(3600)

            prev_price_usdc = price_usdc
            prev_price_usdt = price_usdt
            price_usdt = get_spot_data()
            price_usdc = get_spot_data("USDC/EUR")

        await asyncio.sleep(1)


@router.message(Command('start'))
async def start(message: types.Message):
    await message.answer(text="<b>Welcome to the Bot for everyday EUR/USDT price!\n</b>", parse_mode="HTML")


@router.message()
async def get_chat_id(message: types.Message):
    print("message.chat.id:", message.chat.id)
    print("message.message_thread_id:", message.message_thread_id)






