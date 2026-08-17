import asyncio
import json
import logging
import os
from datetime import datetime, time, timezone
from pathlib import Path

import ccxt
from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUBSCRIPTION_PRICE_STARS = int(os.getenv("SUBSCRIPTION_PRICE_STARS", "100"))
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "3"))
TRIAL_REFRESH_LIMIT_PER_DAY = int(os.getenv("TRIAL_REFRESH_LIMIT_PER_DAY", "5"))

if not 1 <= SUBSCRIPTION_PRICE_STARS <= 10000:
    raise ValueError("SUBSCRIPTION_PRICE_STARS must be between 1 and 10000")
if not 1 <= TRIAL_DAYS <= 30:
    raise ValueError("TRIAL_DAYS must be between 1 and 30")
if not 1 <= TRIAL_REFRESH_LIMIT_PER_DAY <= 100:
    raise ValueError("TRIAL_REFRESH_LIMIT_PER_DAY must be between 1 and 100")

bot = Bot(token=BOT_TOKEN)

router = Router()

TG_USERS = ["454078708", "482953524"]

SUBSCRIPTION_PERIOD_SECONDS = 30 * 24 * 60 * 60
SUBSCRIPTION_PAYLOAD_PREFIX = "spot_info_subscription"
PAID_USERS_FILE = Path(__file__).with_name("paid_users.json")


def load_paid_users():
    if not PAID_USERS_FILE.exists():
        return {}

    try:
        data = json.loads(PAID_USERS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Error loading paid users: %s", error)
        return {}


def save_paid_users():
    temporary_file = PAID_USERS_FILE.with_suffix(".json.tmp")
    temporary_file.write_text(
        json.dumps(paid_users, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_file.replace(PAID_USERS_FILE)


paid_users = load_paid_users()
subscription_lock = asyncio.Lock()


def is_free_user(user_id):
    return str(user_id) in TG_USERS


def has_paid_access(user_id):
    subscription = paid_users.get(str(user_id), {})
    expires_at = int(subscription.get("expires_at", 0))
    return expires_at > int(datetime.now(timezone.utc).timestamp())


def has_trial_access(user_id):
    user_data = paid_users.get(str(user_id), {})
    expires_at = int(user_data.get("trial_expires_at", 0))
    return expires_at > int(datetime.now(timezone.utc).timestamp())


def has_access(user_id):
    return (
        is_free_user(user_id) or has_paid_access(user_id) or has_trial_access(user_id)
    )


async def ensure_trial(user_id):
    if is_free_user(user_id) or str(user_id) in paid_users:
        return False

    async with subscription_lock:
        if str(user_id) in paid_users:
            return False

        started_at = int(datetime.now(timezone.utc).timestamp())
        paid_users[str(user_id)] = {
            "trial_started_at": started_at,
            "trial_expires_at": started_at + TRIAL_DAYS * 24 * 60 * 60,
            "trial_refresh_date": None,
            "trial_refresh_count": 0,
        }
        save_paid_users()
        return True


def get_trial_refreshes_left(user_id):
    if not has_trial_access(user_id):
        return 0

    user_data = paid_users[str(user_id)]
    today = datetime.now(timezone.utc).date().isoformat()
    used = (
        int(user_data.get("trial_refresh_count", 0))
        if user_data.get("trial_refresh_date") == today
        else 0
    )
    return max(0, TRIAL_REFRESH_LIMIT_PER_DAY - used)


async def consume_trial_refresh(user_id):
    if is_free_user(user_id) or has_paid_access(user_id):
        return True

    if not has_trial_access(user_id):
        return False

    async with subscription_lock:
        user_data = paid_users[str(user_id)]
        today = datetime.now(timezone.utc).date().isoformat()

        if user_data.get("trial_refresh_date") != today:
            user_data["trial_refresh_date"] = today
            user_data["trial_refresh_count"] = 0

        used = int(user_data.get("trial_refresh_count", 0))
        if used >= TRIAL_REFRESH_LIMIT_PER_DAY:
            return False

        user_data["trial_refresh_count"] = used + 1
        save_paid_users()
        return True


def get_recipient_ids():
    recipient_ids = {int(user_id) for user_id in TG_USERS}
    recipient_ids.update(
        int(user_id) for user_id in paid_users if has_access(int(user_id))
    )
    return recipient_ids


def build_subscription_payload(user_id):
    return f"{SUBSCRIPTION_PAYLOAD_PREFIX}:{user_id}:{SUBSCRIPTION_PRICE_STARS}"


def parse_subscription_payload(payload):
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != SUBSCRIPTION_PAYLOAD_PREFIX:
        return None

    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


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

subscription_keyboard = types.InlineKeyboardMarkup(
    inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text=(f"⭐ Доступ на 30 днів — {SUBSCRIPTION_PRICE_STARS} Stars"),
                callback_data="buy_subscription",
            )
        ]
    ]
)


def build_subscription_offer():
    return (
        "<b>⭐ Платний доступ</b>\n\n"
        "Порівняння USDT/EUR та USDC/EUR на Bybit, Binance, "
        "OKX і Kraken, погодинні оновлення та ручна кнопка "
        "оновлення.\n\n"
        f"Ціна: <b>{SUBSCRIPTION_PRICE_STARS} Telegram Stars</b> за 30 днів. "
        "Підписка автоматично поновлюється.\n\n"
        "Оплачуючи, ви погоджуєтеся з /terms."
    )


async def send_subscription_offer(chat_id):
    await bot.send_message(
        chat_id,
        build_subscription_offer(),
        parse_mode="HTML",
        reply_markup=subscription_keyboard,
    )


async def create_subscription_link(user_id):
    return await bot.create_invoice_link(
        title="Spot Info — 30 днів",
        description=(
            "30 днів доступу до порівняння цін на Bybit, Binance, OKX і Kraken"
        ),
        payload=build_subscription_payload(user_id),
        currency="XTR",
        prices=[
            types.LabeledPrice(
                label="Доступ на 30 днів",
                amount=SUBSCRIPTION_PRICE_STARS,
            )
        ],
        provider_token="",
        subscription_period=SUBSCRIPTION_PERIOD_SECONDS,
    )


def get_exchange_prices(exchange_name, client):
    prices = {symbol: None for symbol, _ in PRICE_PAIRS}

    try:
        markets = client.load_markets()
    except Exception as error:
        logger.warning("Error loading %s markets: %s", exchange_name, error)
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
        except Exception as error:
            logger.warning(
                "Error fetching %s from %s: %s",
                symbol,
                exchange_name,
                error,
            )

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

        for (exchange_name, _), prices in zip(
            EXCHANGES.items(),
            exchange_prices,
            strict=True,
        ):
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
                message += f"{exchange_name:<10} {'—':>10} {'—':>5} {'—':>8}\n"
                continue

            current = state["current"]
            previous = state["previous"]
            trend, percentage = get_change(current, previous)
            available_prices.append(current)
            message += (
                f"{exchange_name:<10} {current:>10.6f} {trend:>5} {percentage:>8}\n"
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

            for user in get_recipient_ids():
                try:
                    await bot.send_message(
                        user,
                        daily_message,
                        parse_mode="HTML",
                        reply_markup=refresh_keyboard,
                    )
                except Exception as error:
                    logger.warning("Could not send prices to %s: %s", user, error)

            await asyncio.sleep(3600)

        await asyncio.sleep(1)


@router.callback_query(F.data == "refresh_prices")
async def refresh_prices(callback: types.CallbackQuery):
    await ensure_trial(callback.from_user.id)

    if not has_access(callback.from_user.id):
        await callback.answer(
            "Для оновлення потрібен активний доступ",
            show_alert=True,
        )
        await send_subscription_offer(callback.from_user.id)
        return

    if not await consume_trial_refresh(callback.from_user.id):
        await callback.answer(
            f"Ліміт — {TRIAL_REFRESH_LIMIT_PER_DAY} оновлень на добу. "
            "Спробуйте завтра або оформіть /subscribe.",
            show_alert=True,
        )
        return

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


@router.callback_query(F.data == "buy_subscription")
async def buy_subscription(callback: types.CallbackQuery):
    if is_free_user(callback.from_user.id) or has_paid_access(callback.from_user.id):
        await callback.answer("Доступ уже активний", show_alert=True)
        return

    await callback.answer("Створюю рахунок…")
    invoice_link = await create_subscription_link(callback.from_user.id)
    payment_keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"⭐ Оплатити {SUBSCRIPTION_PRICE_STARS} Stars",
                    url=invoice_link,
                )
            ]
        ]
    )
    await bot.send_message(
        callback.from_user.id,
        "Натисніть кнопку нижче, щоб оформити підписку:",
        reply_markup=payment_keyboard,
    )


@router.pre_checkout_query()
async def process_pre_checkout(query: types.PreCheckoutQuery):
    subscription_data = parse_subscription_payload(query.invoice_payload)

    if subscription_data is None:
        await query.answer(ok=False, error_message="Невірний рахунок")
        return

    payload_user_id, payload_price = subscription_data
    is_valid = (
        payload_user_id == query.from_user.id
        and query.currency == "XTR"
        and query.total_amount == payload_price
    )

    if not is_valid:
        await query.answer(
            ok=False,
            error_message="Цей рахунок не належить вам",
        )
        return

    await query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    payment = message.successful_payment
    subscription_data = parse_subscription_payload(payment.invoice_payload)

    if subscription_data is None:
        await message.answer("Не вдалося перевірити платіж. Зверніться в /paysupport.")
        return

    payload_user_id, payload_price = subscription_data
    if (
        payload_user_id != message.from_user.id
        or payment.currency != "XTR"
        or payment.total_amount != payload_price
    ):
        await message.answer("Не вдалося перевірити платіж. Зверніться в /paysupport.")
        return

    expires_at = payment.subscription_expiration_date
    if expires_at is None:
        expires_at = (
            int(datetime.now(timezone.utc).timestamp()) + SUBSCRIPTION_PERIOD_SECONDS
        )

    async with subscription_lock:
        paid_users[str(message.from_user.id)] = {
            "expires_at": expires_at,
            "telegram_payment_charge_id": payment.telegram_payment_charge_id,
            "price_stars": payment.total_amount,
            "state": "active",
        }
        save_paid_users()

    expires_text = datetime.fromtimestamp(expires_at, timezone.utc).strftime(
        "%d.%m.%Y %H:%M UTC"
    )
    await message.answer(
        f"✅ Доступ активовано до <b>{expires_text}</b>.",
        parse_mode="HTML",
    )
    await update_prices()
    await message.answer(
        build_price_message(),
        parse_mode="HTML",
        reply_markup=refresh_keyboard,
    )


@router.subscription()
async def process_subscription_update(update: types.BotSubscriptionUpdated):
    subscription_data = parse_subscription_payload(update.invoice_payload)
    if subscription_data is None or subscription_data[0] != update.user.id:
        return

    async with subscription_lock:
        subscription = paid_users.get(str(update.user.id))
        if subscription is None:
            return
        subscription["state"] = update.state
        save_paid_users()


@router.message(Command("start"))
async def start(message: types.Message):
    trial_created = await ensure_trial(message.from_user.id)

    if not has_access(message.from_user.id):
        await send_subscription_offer(message.chat.id)
        return

    if trial_created:
        await message.answer(
            f"🎁 Активовано безкоштовний доступ на {TRIAL_DAYS} дні.\n"
            f"Доступно {TRIAL_REFRESH_LIMIT_PER_DAY} ручних оновлень на добу."
        )

    await update_prices()
    await message.answer(
        text=build_price_message(),
        parse_mode="HTML",
        reply_markup=refresh_keyboard,
    )


@router.message(Command("subscribe"))
async def subscribe(message: types.Message):
    if is_free_user(message.from_user.id) or has_paid_access(message.from_user.id):
        await message.answer("✅ Доступ уже активний.")
        return
    await send_subscription_offer(message.chat.id)


@router.message(Command("subscription"))
async def subscription_status(message: types.Message):
    if is_free_user(message.from_user.id):
        await message.answer("✅ Для вас активовано безкоштовний доступ.")
        return

    subscription = paid_users.get(str(message.from_user.id))
    if has_paid_access(message.from_user.id):
        expires_at = int(subscription["expires_at"])
        expires_text = datetime.fromtimestamp(expires_at, timezone.utc).strftime(
            "%d.%m.%Y %H:%M UTC"
        )
        state = subscription.get("state", "active")
        renewal = "увімкнено" if state == "active" else "вимкнено"
        await message.answer(
            f"✅ Доступ активний до <b>{expires_text}</b>.\n"
            f"Автопоновлення: <b>{renewal}</b>.",
            parse_mode="HTML",
        )
        return

    if has_trial_access(message.from_user.id):
        expires_at = int(subscription["trial_expires_at"])
        expires_text = datetime.fromtimestamp(expires_at, timezone.utc).strftime(
            "%d.%m.%Y %H:%M UTC"
        )
        await message.answer(
            f"🎁 Пробний доступ активний до <b>{expires_text}</b>.\n"
            f"Ручних оновлень на сьогодні: "
            f"<b>{get_trial_refreshes_left(message.from_user.id)}</b>.",
            parse_mode="HTML",
        )
        return

    if not subscription or not has_access(message.from_user.id):
        await send_subscription_offer(message.chat.id)
        return


@router.message(Command("cancel"))
async def cancel_subscription(message: types.Message):
    if is_free_user(message.from_user.id):
        await message.answer("Ваш безкоштовний доступ не потребує скасування.")
        return

    subscription = paid_users.get(str(message.from_user.id))
    if not subscription or not has_paid_access(message.from_user.id):
        await message.answer("У вас немає активної підписки.")
        return

    charge_id = subscription.get("telegram_payment_charge_id")
    if not charge_id:
        await message.answer("Не вдалося скасувати підписку. Зверніться в /paysupport.")
        return

    await bot.edit_user_star_subscription(
        user_id=message.from_user.id,
        telegram_payment_charge_id=charge_id,
        is_canceled=True,
    )
    async with subscription_lock:
        subscription["state"] = "canceled"
        save_paid_users()

    expires_at = int(subscription["expires_at"])
    expires_text = datetime.fromtimestamp(expires_at, timezone.utc).strftime(
        "%d.%m.%Y %H:%M UTC"
    )
    await message.answer(
        f"Автопоновлення вимкнено. Доступ залишається до <b>{expires_text}</b>.",
        parse_mode="HTML",
    )


@router.message(Command("terms"))
async def terms(message: types.Message):
    await message.answer(
        "<b>Умови підписки</b>\n\n"
        f"Новим користувачам надається {TRIAL_DAYS}-денний пробний доступ з "
        f"лімітом {TRIAL_REFRESH_LIMIT_PER_DAY} ручних оновлень на добу.\n\n"
        f"Вартість: {SUBSCRIPTION_PRICE_STARS} Telegram Stars за 30 днів.\n"
        "Підписка автоматично поновлюється кожні 30 днів, доки ви не "
        "виконаєте /cancel. Після скасування доступ діє до кінця оплаченого "
        "періоду.\n\n"
        "Котирування мають інформаційний характер і не є фінансовою порадою.",
        parse_mode="HTML",
    )


@router.message(Command("paysupport"))
async def payment_support(message: types.Message):
    await message.answer(
        "З питань оплати та повернення коштів зверніться до "
        '<a href="tg://user?id=454078708">підтримки</a>.',
        parse_mode="HTML",
    )


@router.message()
async def fallback_message(message: types.Message):
    trial_created = False
    if message.from_user:
        trial_created = await ensure_trial(message.from_user.id)

    if trial_created:
        await message.answer(
            f"🎁 Активовано безкоштовний доступ на {TRIAL_DAYS} дні. "
            "Натисніть /start, щоб побачити ціни."
        )
        return

    if message.from_user and not has_access(message.from_user.id):
        await send_subscription_offer(message.chat.id)
        return

    await message.answer("Використайте /start, щоб побачити актуальні ціни.")
