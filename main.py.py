import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# НАСТРОЙКИ: вставьте ваш токен в кавычки вместо текста ниже
TOKEN = "8870885678:AAFc5_FipzaQVWRDoFMOlZR-NjpTQD_rAi421:43"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("schedule_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            day_of_week INTEGER,
            time_str TEXT,
            task_text TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- СОСТОЯНИЯ ДЛЯ ДОБАВЛЕНИЯ РАСПИСАНИЯ ---
class AddSchedule(StatesGroup):
    waiting_for_day = State()
    waiting_for_time = State()
    waiting_for_task = State()

DAYS_MAP = {
    "Понедельник": 0,
    "Вторник": 1,
    "Среда": 2,
    "Четверг": 3,
    "Пятница": 4,
    "Суббота": 5,
    "Воскресенье": 6
}

# --- КОМАНДЫ ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я умный бот-напоминалка.\n\n"
        "📅 Доступные команды:\n"
        "/add — Добавить новое напоминание\n"
        "/my — Посмотреть мои задачи"
    )

@dp.message(Command("my"))
async def cmd_my(message: Message):
    conn = sqlite3.connect("schedule_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT day_of_week, time_str, task_text FROM schedules WHERE user_id = ?", (message.from_user.id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await message.answer("У вас пока нет сохраненных задач. Нажмите /add, чтобы добавить.")
        return

    days_reverse = {v: k for k, v in DAYS_MAP.items()}
    text = "📋 **Ваши задачи:**\n\n"
    for day, t, task in rows:
        day_name = days_reverse.get(day, "День")
        text += f"▪️ {day_name} в {t} — {task}\n"

    await message.answer(text, parse_mode="Markdown")

# --- ПРОЦЕСС ДОБАВЛЕНИЯ ЧЕРЕЗ КНОПКИ ---
@dp.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Понедельник", callback_data="day_0"), InlineKeyboardButton(text="Вторник", callback_data="day_1")],
        [InlineKeyboardButton(text="Среда", callback_data="day_2"), InlineKeyboardButton(text="Четверг", callback_data="day_3")],
        [InlineKeyboardButton(text="Пятница", callback_data="day_4"), InlineKeyboardButton(text="Суббота", callback_data="day_5")],
        [InlineKeyboardButton(text="Воскресенье", callback_data="day_6")]
    ])
    await message.answer("Выберите день недели для напоминания:", reply_markup=keyboard)
    await state.set_state(AddSchedule.waiting_for_day)

@dp.callback_query(F.data.startswith("day_"), AddSchedule.waiting_for_day)
async def process_day(callback: CallbackQuery, state: FSMContext):
    day_num = int(callback.data.split("_")[1])
    await state.update_data(day_of_week=day_num)
    
    await callback.message.edit_text("Введите время напоминания в формате ЧЧ:MM (например, `07:40` или `01:40`):", parse_mode="Markdown")
    await state.set_state(AddSchedule.waiting_for_time)
    await callback.answer()

@dp.message(AddSchedule.waiting_for_time)
async def process_time(message: Message, state: FSMContext):
    time_str = message.text.strip()
    if len(time_str) != 5 or time_str[2] != ':':
        await message.answer("Неверный формат! Введите время строго в формате ЧЧ:MM (например, 07:00):")
        return
    
    await state.update_data(time_str=time_str)
    await message.answer("Теперь отправьте текст напоминания (например: *Урок химии* или *Выключить компьютер!*):", parse_mode="Markdown")
    await state.set_state(AddSchedule.waiting_for_task)

@dp.message(AddSchedule.waiting_for_task)
async def process_task(message: Message, state: FSMContext):
    task_text = message.text.strip()
    data = await state.get_data()
    
    user_id = message.from_user.id
    day_of_week = data["day_of_week"]
    time_str = data["time_str"]

    conn = sqlite3.connect("schedule_bot.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO schedules (user_id, day_of_week, time_str, task_text) VALUES (?, ?, ?, ?)",
        (user_id, day_of_week, time_str, task_text)
    )
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer("✅ Успешно! Задача сохранена. Бот будет присылать её в нужное время.")

# --- ПЛАНИРОВЩИК РАССЫЛКИ ---
async def check_schedule(scheduler_bot: Bot):
    from datetime import datetime
    now_dt = datetime.now()
    current_day = now_dt.weekday() # 0 - Пн, 6 - Вс
    current_time = now_dt.strftime("%H:%M")

    conn = sqlite3.connect("schedule_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, time_str, task_text FROM schedules WHERE day_of_week = ? AND time_str = ?", (current_day, current_time))
    rows = cursor.fetchall()
    conn.close()

    for user_id, t, task in rows:
        try:
            await scheduler_bot.send_message(chat_id=user_id, text=f"⏰ Напоминание ({t}): {task}")
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

async def main():
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(check_schedule, "interval", minutes=1, args=[bot])
    
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())