"""Tugmalar: pastki menyu (reply) va tez-tez ishlatiladigan inline tugmalar."""
from aiogram import F
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# O'quvchi menyusi
BTN_TASKS = "📚 Vazifalar"
BTN_RESULTS = "📊 Natijalarim"

# O'qituvchi menyusi
BTN_NEWTASK = "➕ Yangi vazifa"
BTN_ADMIN_TASKS = "📋 Vazifalar"
BTN_PENDING = "📥 Tekshirilmagan"
BTN_STUDENTS = "👥 O'quvchilar"
BTN_BACKUP = "🗂 Zahira nusxa"
BTN_SETTINGS = "⚙️ Sozlamalar"
BTN_STATS = "📊 Statistika"

MENU_BUTTONS = (
    BTN_TASKS,
    BTN_RESULTS,
    BTN_NEWTASK,
    BTN_ADMIN_TASKS,
    BTN_PENDING,
    BTN_STUDENTS,
    BTN_BACKUP,
    BTN_SETTINGS,
    BTN_STATS,
)

# Holat (FSM) ichidagi matn handlerlari uchun filtrlar. Har doim `F.text` dan keyin qo'yiladi.
# Menyu tugmasi bosilsa, u javob matni sifatida qabul qilinmaydi.
NOT_MENU = ~F.text.in_(MENU_BUTTONS)
# "/start", "/cancel" kabi buyruqlar javob matni bo'lib qolmasin.
NOT_CMD = ~F.text.startswith("/")
# Muddat/izoh bosqichida faqat /skip buyrug'iga ruxsat beriladi (asosiy yo'l: tugma).
TEXT_OR_SKIP = ~F.text.startswith("/") | F.text.in_(("/skip",))


def student_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_TASKS), KeyboardButton(text=BTN_RESULTS)]],
        resize_keyboard=True,
    )


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_NEWTASK), KeyboardButton(text=BTN_ADMIN_TASKS)],
            [KeyboardButton(text=BTN_PENDING), KeyboardButton(text=BTN_STUDENTS)],
            [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_BACKUP)],
            [KeyboardButton(text=BTN_SETTINGS)],
        ],
        resize_keyboard=True,
    )


def cancel_kb(skip_text: str | None = None) -> InlineKeyboardMarkup:
    """«Bekor qilish» tugmasi, ixtiyoriy ravishda «o'tkazib yuborish» tugmasi bilan."""
    row = []
    if skip_text:
        row.append(InlineKeyboardButton(text=skip_text, callback_data="skip"))
    row.append(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel"))
    return InlineKeyboardMarkup(inline_keyboard=[row])
