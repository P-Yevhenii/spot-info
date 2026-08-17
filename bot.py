import asyncio
from datetime import datetime, time

from aiogram import Bot, F, types
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from dotenv import load_dotenv
import os
import ccxt

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')

bot = Bot(token=BOT_TOKEN)

router = Router()

TG_USERS = ["454078708", "482953524"]

EXCHANGES = {
    "Bybit": ccxt.bybit({"enableRateLimit": True}),
    "Binance": ccxt.binance({"enableRateLimit": True}),
    "OKX": ccxt.okx({"enableRateLimit": True}),
    "Kraken": ccxt.kraken({"enableRateLimit": True}),
}

target_start = time(hour=6, minute=0, second=0)
target_end = time(hour=23, minute=0, second=0)

PRICE_PAIRS = (
    ("USDT/EUR", "💲/🇪🇺"),
    ("USDC/EUR", "💵/🇪🇺"),
)

price_state = {
    symbol: {
        exchange_name: {
            "current": None,
            "previous": None,
            "available": False,
        }
        for exchange_name in EXCHANGES
    }
    for symbol, _ in PRICE_PAIRS
}
price_update_lock = asyncio.Lock()

refresh_keyboard = types.InlineKeyboardMarkup(
    inline_keyboard=[
        [types.InlineKeyboardButton(text="🔄 Оновити", callback_data="refresh_prices")]
    ]
)


def get_exchange_prices(exchange_name, client):
    prices = {symbol: None for symbol, _ in PRICE_PAIRS}

    try:
        markets = client.load_markets()
    except Exception as e:
        print(f"Error loading {exchange_name} markets: {e}")
        return prices

    for symbol, _ in PRICE_PAIRS:
        base, quote = symbol.split("/")
        inverse_symbol = f"{quote}/{base}"

        try:
            if symbol in markets:
                ticker = client.fetch_ticker(symbol)
                price = ticker.get("last")
            elif inverse_symbol in markets:
                ticker = client.fetch_ticker(inverse_symbol)
                inverse_price = ticker.get("last")
                price = 1 / inverse_price if inverse_price else None
            else:
                continue

            prices[symbol] = float(price) if price is not None else None
        except Exception as e:
            print(f"Error fetching {symbol} from {exchange_name}: {e}")

    return prices


def get_change(current, previous):
    if current is None or previous is None or previous == 0:
        return "➡️", "—"

    absolute = current - previous
    percentage = absolute / previous * 100

    if absolute > 0:
        trend = "⬆️"
    elif absolute < 0:
        trend = "⬇️"
    else:
        trend = "➡️"

    return trend, f"{percentage:+.2f}%"


async def update_prices():
    async with price_update_lock:
        exchange_prices = await asyncio.gather(
            *(
                asyncio.to_thread(get_exchange_prices, exchange_name, client)
                for exchange_name, client in EXCHANGES.items()
            )
        )

        for (exchange_name, _), prices in zip(EXCHANGES.items(), exchange_prices):
            for symbol, _ in PRICE_PAIRS:
                state = price_state[symbol][exchange_name]
                price = prices[symbol]

                if price is None:
                    state["available"] = False
                    continue

                state["previous"] = state["current"]
                state["current"] = price
                state["available"] = True


def build_price_message():
    message = "<b>📊 Market spot comparison</b>\n\n<pre>"

    for symbol, icon in PRICE_PAIRS:
        message += f"{icon} {symbol}\n"
        message += f"{'Exchange':<10} {'Price':>10} {'Trend':>5} {'%':>8}\n"
        message += "-" * 36 + "\n"
        available_prices = []

        for exchange_name in EXCHANGES:
            state = price_state[symbol][exchange_name]

            if not state["available"]:
                message += (
                    f"{exchange_name:<10} {'—':>10} {'—':>5} {'—':>8}\n"
                )
                continue

            current = state["current"]
            previous = state["previous"]
            trend, percentage = get_change(current, previous)
            available_prices.append(current)
            message += (
                f"{exchange_name:<10} {current:>10.6f} {trend:>5} "
                f"{percentage:>8}\n"
            )

        if len(available_prices) >= 2:
            lowest = min(available_prices)
            highest = max(available_prices)
            spread = (highest - lowest) / lowest * 100
            message += f"{'Spread':<10} {'':>10} {'':>5} {spread:>7.2f}%\n"

        message += "\n"

    return message + "</pre>"


async def scheduled_message():
    while True:
        now = datetime.now().time()
        if target_start <= now <= target_end:
            await update_prices()
            daily_message = build_price_message()

            for user in TG_USERS:
                try:
                    await bot.send_message(
                        user,
                        daily_message,
                        parse_mode="HTML",
                        reply_markup=refresh_keyboard,
                    )
                except Exception as e:
                    print(f"User not start his chat with bot: {e}")

            """await bot.send_message(
                chat_id="-1002905214084",
                message_thread_id=203,
                text=daily_message,
                parse_mode="HTML",
            )"""
            await asyncio.sleep(3600)

        await asyncio.sleep(1)


@router.callback_query(F.data == "refresh_prices")
async def refresh_prices(callback: types.CallbackQuery):
    await callback.answer("Оновлюю ціни…")
    await update_prices()

    if callback.message is None:
        return

    try:
        await callback.message.edit_text(
            build_price_message(),
            parse_mode="HTML",
            reply_markup=refresh_keyboard,
        )
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise


@router.message(Command('start'))
async def start(message: types.Message):
    await update_prices()
    await message.answer(
        text=build_price_message(),
        parse_mode="HTML",
        reply_markup=refresh_keyboard,
    )


@router.message()
async def get_chat_id(message: types.Message):
    print("message.chat.id:", message.chat.id)
    print("message.message_thread_id:", message.message_thread_id)

