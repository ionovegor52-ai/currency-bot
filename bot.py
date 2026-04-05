import asyncio
import aiohttp
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ========== ТВОЙ ТОКЕН ==========
BOT_TOKEN = "ТВОЙ_ТОКЕН_СЮДА"  # ВСТАВЬ ТОКЕН ОТ @BotFather

# API для курсов валют
API_URL = "https://api.exchangerate-api.com/v4/latest/USD"

# Популярные валюты
CURRENCIES = ["USD", "EUR", "RUB", "GBP", "JPY", "CNY", "TRY", "KZT", "UAH", "BYN"]

# Хранилище данных
users_data = {}
DATA_FILE = "users_data.json"

def load_data():
    global users_data
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            users_data = json.load(f)

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

def get_user(user_id):
    uid = str(user_id)
    if uid not in users_data:
        users_data[uid] = {"history": [], "favorites": []}
        save_data()
    return users_data[uid]

def save_user(user_id):
    save_data()

# Кеш курсов
rates_cache = {"data": None, "time": 0}

async def get_rates():
    import time
    now = time.time()
    if rates_cache["data"] and (now - rates_cache["time"]) < 60:
        return rates_cache["data"]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    rates_cache = {"data": data.get("rates", {}), "time": now}
                    return rates_cache["data"]
    except:
        return rates_cache["data"] if rates_cache["data"] else {}
    return {}

async def convert(amount, from_curr, to_curr):
    rates = await get_rates()
    if from_curr not in rates or to_curr not in rates:
        return None
    if from_curr == "USD":
        return round(amount * rates[to_curr], 2)
    else:
        usd = amount / rates[from_curr]
        return round(usd * rates[to_curr], 2)

# Состояния
class ConvertState(StatesGroup):
    waiting_amount = State()
    waiting_from = State()
    waiting_to = State()

# Клавиатуры
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
    items = 8
    start = page * items
    all_curr = CURRENCIES.copy()
    if exclude:
        all_curr = [c for c in all_curr if c != exclude]
    currencies = all_curr[start:start+items]
    buttons = [[InlineKeyboardButton(text=c, callback_data=f"{prefix}_{c}")] for c in currencies]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"{prefix}_page_{page-1}"))
    if start + items < len(all_curr):
        nav.append(InlineKeyboardButton(text="Вперед ▶", callback_data=f"{prefix}_page_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Создаём бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def start_command(message: Message):
    get_user(message.from_user.id)
    await message.answer(
        "💱 *Конвертер валют*\n\n"
        "Я умею конвертировать USD, EUR, RUB, GBP и другие валюты.\n\n"
        "👇 Выбери действие:",
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
    await callback.message.edit_text(
        "📌 Выбери валюту, *из которой* конвертируем:",
        reply_markup=currency_keyboard("from"),
        parse_mode="Markdown"
    )
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
    await callback.message.edit_text(
        f"📌 Из {curr} → теперь выбери валюту, *в которую* конвертируем:",
        reply_markup=currency_keyboard("to", exclude=curr),
        parse_mode="Markdown"
    )
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
    await callback.message.edit_text("💰 Введи сумму для конвертации:", reply_markup=None)
    await callback.answer()

@dp.message(ConvertState.waiting_amount)
async def amount_entered(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введи корректное число, например: 100 или 50.75")
        return
    
    data = await state.get_data()
    from_curr = data.get("from_curr")
    to_curr = data.get("to_curr")
    
    await message.bot.send_chat_action(message.chat.id, "typing")
    
    result = await convert(amount, from_curr, to_curr)
    if result is None:
        await message.answer("❌ Ошибка получения курсов. Попробуй позже.")
        return
    
    user = get_user(message.from_user.id)
    user["history"].insert(0, {
        "amount": amount,
        "from": from_curr,
        "to": to_curr,
        "result": result,
        "date": datetime.now().strftime("%d.%m.%Y %H:%M")
    })
    user["history"] = user["history"][:20]
    save_user(message.from_user.id)
    
    text = f"💱 *{amount} {from_curr}* = *{result} {to_curr}*\n\n"
    text += f"📈 Курс: 1 {from_curr} ≈ {round(result/amount, 4)} {to_curr}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ В избранное", callback_data=f"fav_{from_curr}_{to_curr}")],
        [InlineKeyboardButton(text="🔄 Новая конвертация", callback_data="convert")],
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
        await callback.answer("⭐ Добавлено в избранное!", show_alert=True)
    else:
        await callback.answer("Уже в избранном", show_alert=True)

@dp.callback_query(F.data == "favorites")
async def show_favorites(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    favs = user.get("favorites", [])
    if not favs:
        await callback.message.edit_text("⭐ У тебя пока нет избранных пар", reply_markup=main_menu())
        await callback.answer()
        return
    buttons = []
    for pair in favs:
        f, t = pair.split("_")
        buttons.append([InlineKeyboardButton(text=f"💱 {f} → {t}", callback_data=f"use_{pair}")])
    buttons.append([InlineKeyboardButton(text="🔙 Меню", callback_data="menu")])
    await callback.message.edit_text("⭐ *Избранное:*", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("use_"))
async def use_favorite(callback: CallbackQuery, state: FSMContext):
    pair = callback.data.replace("use_", "")
    f, t = pair.split("_")
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
    text = "📜 *Последние конвертации:*\n\n"
    for i, h in enumerate(history[:10], 1):
        text += f"{i}. {h['amount']} {h['from']} → {h['result']} {h['to']}\n   _{h['date']}_\n\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "rates")
async def show_rates(callback: CallbackQuery):
    await callback.message.bot.send_chat_action(callback.message.chat.id, "typing")
    rates = await get_rates()
    if not rates:
        await callback.message.edit_text("❌ Не удалось получить курсы", reply_markup=main_menu())
        await callback.answer()
        return
    text = "📊 *Курсы валют к USD:*\n\n"
    for c in ["EUR", "RUB", "GBP", "JPY", "CNY", "TRY", "KZT", "UAH"]:
        if c in rates:
            text += f"• 1 USD = {rates[c]:.2f} {c}\n"
    text += f"\n🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    text = (
        "❓ *Помощь*\n\n"
        "📌 *Команды:*\n"
        "/start — Главное меню\n\n"
        "📌 *Как пользоваться:*\n"
        "1. Нажми «Конвертировать»\n"
        "2. Выбери из какой валюты\n"
        "3. Выбери в какую валюту\n"
        "4. Введи сумму\n\n"
        "📌 *Фишки:*\n"
        "• Сохранение истории\n"
        "• Избранные пары\n"
        "• Актуальные курсы\n\n"
        "👨‍💻 Создано для портфолио"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu())
    await callback.answer()

# ========== ЗАПУСК ==========
async def main():
    load_data()
    print("✅ Бот запущен на Render!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())