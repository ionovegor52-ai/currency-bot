import asyncio
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web
import aiohttp

# ========== ТОКЕН И URL ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
RENDER_URL = os.environ.get("RENDER_URL", "https://твой-бот.onrender.com")  # ЗАМЕНИ НА СВОЙ URL

# ========== КУРСЫ ВАЛЮТ ==========
RATES = {
    "USD": 1.0, "EUR": 0.92, "RUB": 88.50, "GBP": 0.79,
    "JPY": 150.20, "CNY": 7.25, "TRY": 32.10, "KZT": 450.00,
    "UAH": 41.20, "BYN": 3.27
}
CURRENCIES = list(RATES.keys())
DATA_FILE = "users_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users_data = load_data()

def get_user(user_id):
    uid = str(user_id)
    if uid not in users_data:
        users_data[uid] = {"history": [], "favorites": []}
        save_data(users_data)
    return users_data[uid]

def save_user(user_id):
    save_data(users_data)

def convert(amount, from_curr, to_curr):
    if from_curr not in RATES or to_curr not in RATES:
        return None
    usd_value = amount / RATES[from_curr]
    result = usd_value * RATES[to_curr]
    return round(result, 2)

# ========== СОСТОЯНИЯ ==========
class ConvertState(StatesGroup):
    waiting_amount = State()
    waiting_from = State()
    waiting_to = State()

# ========== КЛАВИАТУРЫ ==========
def main_menu():
    buttons = [
        [InlineKeyboardButton(text="💱 Конвертировать", callback_data="convert")],
        [InlineKeyboardButton(text="⭐ Избранное", callback_data="favorites")],
        [InlineKeyboardButton(text="📜 История", callback_data="history")],
        [InlineKeyboardButton(text="📊 Курсы", callback_data="rates")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def currency_keyboard(prefix, exclude=None, page=0):
    items = 5
    start = page * items
    all_curr = CURRENCIES.copy()
    if exclude:
        all_curr = [c for c in all_curr if c != exclude]
    currencies = all_curr[start:start+items]
    buttons = [[InlineKeyboardButton(text=c, callback_data=f"{prefix}_{c}")] for c in currencies]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"{prefix}_page_{page-1}"))
    if start + items < len(all_curr):
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"{prefix}_page_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ========== СОЗДАЁМ БОТА ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start_command(message: Message):
    get_user(message.from_user.id)
    await message.answer(
        "💱 *Конвертер валют*\n\nДоступны: USD, EUR, RUB, GBP, JPY, CNY, TRY, KZT, UAH, BYN\n\n👇 Выбери действие:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.message.edit_text("💱 Главное меню:", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "convert")
async def convert_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConvertState.waiting_from)
    await callback.message.edit_text("📌 Выбери валюту *из которой*:", reply_markup=currency_keyboard("from"), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(ConvertState.waiting_from, F.data.startswith("from_"))
async def from_selected(callback: CallbackQuery, state: FSMContext):
    if "page" in callback.data:
        page = int(callback.data.split("_")[2])
        await callback.message.edit_reply_markup(reply_markup=currency_keyboard("from", page=page))
        await callback.answer()
        return
    curr = callback.data.split("_")[1]
    await state.update_data(from_curr=curr)
    await state.set_state(ConvertState.waiting_to)
    await callback.message.edit_text(f"📌 Из {curr} → выбери *в какую*:", reply_markup=currency_keyboard("to", exclude=curr), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(ConvertState.waiting_to, F.data.startswith("to_"))
async def to_selected(callback: CallbackQuery, state: FSMContext):
    if "page" in callback.data:
        page = int(callback.data.split("_")[2])
        data = await state.get_data()
        await callback.message.edit_reply_markup(reply_markup=currency_keyboard("to", exclude=data.get("from_curr"), page=page))
        await callback.answer()
        return
    curr = callback.data.split("_")[1]
    await state.update_data(to_curr=curr)
    await state.set_state(ConvertState.waiting_amount)
    await callback.message.edit_text("💰 Введи сумму:", reply_markup=None)
    await callback.answer()

@dp.message(ConvertState.waiting_amount)
async def amount_entered(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введи число, например 100")
        return
    data = await state.get_data()
    from_curr = data.get("from_curr")
    to_curr = data.get("to_curr")
    result = convert(amount, from_curr, to_curr)
    if result is None:
        await message.answer("❌ Ошибка конвертации")
        return
    user = get_user(message.from_user.id)
    user["history"].insert(0, {"amount": amount, "from": from_curr, "to": to_curr, "result": result, "date": datetime.now().strftime("%d.%m.%Y %H:%M")})
    user["history"] = user["history"][:20]
    save_user(message.from_user.id)
    text = f"💱 *{amount} {from_curr}* = *{result} {to_curr}*\n\n📈 1 {from_curr} ≈ {round(result/amount, 4)} {to_curr}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ В избранное", callback_data=f"fav_{from_curr}_{to_curr}")],
        [InlineKeyboardButton(text="🔄 Новая", callback_data="convert")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="menu")]
    ])
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
    await state.clear()

@dp.callback_query(F.data.startswith("fav_"))
async def add_favorite(callback: CallbackQuery):
    pair = callback.data.replace("fav_", "")
    user = get_user(callback.from_user.id)
    if pair not in user["favorites"]:
        user["favorites"].append(pair)
        save_user(callback.from_user.id)
        await callback.answer("⭐ Добавлено!", show_alert=True)
    else:
        await callback.answer("Уже есть", show_alert=True)

@dp.callback_query(F.data == "favorites")
async def show_favorites(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    favs = user.get("favorites", [])
    if not favs:
        await callback.message.edit_text("⭐ Нет избранных пар", reply_markup=main_menu())
        await callback.answer()
        return
    buttons = [[InlineKeyboardButton(text=f"💱 {f}→{t}", callback_data=f"use_{f}_{t}")] for f,t in [pair.split("_") for pair in favs]]
    buttons.append([InlineKeyboardButton(text="🔙 Меню", callback_data="menu")])
    await callback.message.edit_text("⭐ *Избранное:*", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("use_"))
async def use_favorite(callback: CallbackQuery, state: FSMContext):
    _, f, t = callback.data.split("_")
    await state.update_data(from_curr=f, to_curr=t)
    await state.set_state(ConvertState.waiting_amount)
    await callback.message.edit_text(f"💰 {f} → {t}\nВведи сумму:")
    await callback.answer()

@dp.callback_query(F.data == "history")
async def show_history(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    history = user.get("history", [])
    if not history:
        await callback.message.edit_text("📜 История пуста", reply_markup=main_menu())
        await callback.answer()
        return
    text = "📜 *Последние 10:*\n\n"
    for i, h in enumerate(history[:10], 1):
        text += f"{i}. {h['amount']} {h['from']} → {h['result']} {h['to']}\n   _{h['date']}_\n\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "rates")
async def show_rates(callback: CallbackQuery):
    text = "📊 *Курсы к USD:*\n\n"
    for curr, rate in RATES.items():
        text += f"• 1 USD = {rate:.2f} {curr}\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    text = "❓ *Помощь*\n\n/start — меню\n\n1. Нажми «Конвертировать»\n2. Выбери валюты\n3. Введи сумму\n\n⭐ Избранное — быстрый доступ\n📜 История — последние операции"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu())
    await callback.answer()

# ========== ВЕБ-СЕРВЕР ДЛЯ RENDER (обязательно) ==========
async def health_check(request):
    return web.Response(text="✅ Бот работает")

async def self_ping():
    """Каждые 10 минут бот пингует сам себя"""
    while True:
        await asyncio.sleep(600)  # 10 минут
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RENDER_URL, timeout=10) as resp:
                    print(f"[SELF-PING] {resp.status} - {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"[SELF-PING] Ошибка: {e}")

async def start_web():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    port = int(os.environ.get('PORT', 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✅ Веб-сервер на порту {port}")

# ========== ЗАПУСК ==========
async def main():
    print("✅ Бот запущен!")
    print(f"📍 Адрес: {RENDER_URL}")
    
    # Запускаем веб-сервер
    await start_web()
    
    # Запускаем самопинг
    asyncio.create_task(self_ping())
    print("🔄 Самопинг запущен (каждые 10 минут)")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())