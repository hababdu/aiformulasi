import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

import db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

router = Router()

BTN_TASKS = "📚 Vazifalar"
BTN_RESULTS = "📊 Natijalarim"


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def student_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_TASKS), KeyboardButton(text=BTN_RESULTS)]],
        resize_keyboard=True,
    )


# ======================= FSM =======================
class NewTask(StatesGroup):
    title = State()
    description = State()
    deadline = State()


class Submit(StatesGroup):
    waiting = State()


class Review(StatesGroup):
    comment = State()


# ======================= /start =======================
@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    u = message.from_user
    db.upsert_user(u.id, u.full_name, u.username)
    if is_admin(u.id):
        await message.answer(
            "Salom, o'qituvchi! 👨‍🏫\n\n"
            "/newtask – yangi vazifa berish\n"
            "/tasks – faol vazifalar\n"
            "/pending – tekshirilmagan ishlar\n"
            "/close <id> – vazifani yopish"
        )
    else:
        await message.answer(
            f"Salom, {u.first_name}! 👋\n"
            "Bu yerda vazifalarni topshirishingiz va natijalarni ko'rishingiz mumkin.",
            reply_markup=student_menu(),
        )


# ======================= TEACHER: yangi vazifa =======================
@router.message(Command("newtask"), F.func(lambda m: is_admin(m.from_user.id)))
async def newtask_start(message: Message, state: FSMContext):
    await state.set_state(NewTask.title)
    await message.answer("Vazifa nomini yozing:")


@router.message(NewTask.title, F.text)
async def newtask_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(NewTask.description)
    await message.answer("Vazifa tavsifini yozing (nima qilish kerak):")


@router.message(NewTask.description, F.text)
async def newtask_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(NewTask.deadline)
    await message.answer("Topshirish muddati (masalan: 12-noyabr 23:59). Muddat yo'q bo'lsa /skip yozing:")


@router.message(NewTask.deadline, F.text)
async def newtask_deadline(message: Message, state: FSMContext, bot: Bot):
    deadline = None if message.text.strip() == "/skip" else message.text.strip()
    data = await state.get_data()
    await state.clear()
    task_id = db.add_task(data["title"], data["description"], deadline)
    await message.answer(f"✅ Vazifa #{task_id} yaratildi. O'quvchilarga yuborilmoqda...")

    text = f"📢 Yangi vazifa!\n\n{data['title']}\n\n{data['description']}"
    if deadline:
        text += f"\n\n⏰ Muddat: {deadline}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📤 Topshirish", callback_data=f"submit:{task_id}")]]
    )
    sent = 0
    for uid in db.all_user_ids():
        if is_admin(uid):
            continue
        try:
            await bot.send_message(uid, text, reply_markup=kb)
            sent += 1
        except Exception:
            pass
    await message.answer(f"📨 {sent} ta o'quvchiga yuborildi.")


# ======================= TEACHER: ro'yxatlar =======================
@router.message(Command("tasks"), F.func(lambda m: is_admin(m.from_user.id)))
async def admin_tasks(message: Message):
    tasks = db.active_tasks()
    if not tasks:
        await message.answer("Faol vazifalar yo'q.")
        return
    pend = db.pending_count_by_task()
    lines = [
        f"#{t['id']} – {t['title']} (tekshirilmagan: {pend.get(t['id'], 0)})"
        for t in tasks
    ]
    await message.answer("\n".join(lines))


@router.message(Command("close"), F.func(lambda m: is_admin(m.from_user.id)))
async def admin_close(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Foydalanish: /close <vazifa_id>")
        return
    ok = db.close_task(int(parts[1]))
    await message.answer("✅ Vazifa yopildi." if ok else "Bunday vazifa topilmadi.")


def review_keyboard(sub_id: int) -> InlineKeyboardMarkup:
    grades = [
        InlineKeyboardButton(text=g, callback_data=f"grade:{sub_id}:{g}")
        for g in ("5", "4", "3", "2")
    ]
    redo = [InlineKeyboardButton(text="🔁 Qayta topshirsin", callback_data=f"grade:{sub_id}:redo")]
    return InlineKeyboardMarkup(inline_keyboard=[grades, redo])


async def send_submission(bot: Bot, chat_id: int, sub_id: int):
    s = db.get_submission(sub_id)
    if not s:
        return
    who = s["full_name"] + (f" (@{s['username']})" if s["username"] else "")
    header = f"📝 #{s['id']} | {s['task_title']}\n👤 {who}\n"
    body = s["text"] or ""
    kb = review_keyboard(s["id"])
    if s["content_type"] == "photo":
        await bot.send_photo(chat_id, s["file_id"], caption=(header + body)[:1024], reply_markup=kb)
    elif s["content_type"] == "document":
        await bot.send_document(chat_id, s["file_id"], caption=(header + body)[:1024], reply_markup=kb)
    else:
        await bot.send_message(chat_id, (header + "\n" + body)[:4096], reply_markup=kb)


@router.message(Command("pending"), F.func(lambda m: is_admin(m.from_user.id)))
async def admin_pending(message: Message, bot: Bot):
    rows = db.pending_submissions()
    if not rows:
        await message.answer("Tekshirilmagan ishlar yo'q 🎉")
        return
    for r in rows:
        await send_submission(bot, message.chat.id, r["id"])


# ======================= TEACHER: baholash =======================
@router.callback_query(F.data.startswith("grade:"))
async def on_grade(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Faqat o'qituvchi uchun", show_alert=True)
        return
    _, sub_id, grade = cb.data.split(":")
    s = db.get_submission(int(sub_id))
    if not s or s["status"] != "pending":
        await cb.answer("Bu ish allaqachon tekshirilgan.", show_alert=True)
        return
    await state.set_state(Review.comment)
    await state.update_data(sub_id=int(sub_id), grade=grade)
    label = "Qayta topshirish" if grade == "redo" else f"Baho: {grade}"
    await cb.message.answer(f"{label}. Izoh yozing yoki /skip:")
    await cb.answer()


@router.message(Review.comment, F.text)
async def on_comment(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    comment = None if message.text.strip() == "/skip" else message.text.strip()
    s = db.get_submission(data["sub_id"])
    if not s or s["status"] != "pending":
        await message.answer("Bu ish allaqachon tekshirilgan.")
        return

    grade = data["grade"]
    if grade == "redo":
        db.review_submission(s["id"], "redo", None, comment)
        text = f"🔁 «{s['task_title']}» vazifangizni qayta topshiring."
    else:
        db.review_submission(s["id"], "graded", grade, comment)
        text = f"✅ «{s['task_title']}» vazifangiz tekshirildi.\nBaho: {grade}"
    if comment:
        text += f"\n💬 Izoh: {comment}"

    try:
        await bot.send_message(s["user_id"], text)
        await message.answer("Natija o'quvchiga yuborildi ✅")
    except Exception:
        await message.answer("Saqlandi, lekin o'quvchiga xabar yuborib bo'lmadi.")


# ======================= STUDENT: vazifalar =======================
@router.message(F.text == BTN_TASKS)
async def student_tasks(message: Message):
    tasks = db.active_tasks()
    if not tasks:
        await message.answer("Hozircha faol vazifalar yo'q.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t["title"], callback_data=f"task:{t['id']}")]
            for t in tasks
        ]
    )
    await message.answer("Vazifani tanlang:", reply_markup=kb)


@router.callback_query(F.data.startswith("task:"))
async def show_task(cb: CallbackQuery):
    t = db.get_task(int(cb.data.split(":")[1]))
    if not t:
        await cb.answer("Vazifa topilmadi", show_alert=True)
        return
    text = f"{t['title']}\n\n{t['description']}"
    if t["deadline"]:
        text += f"\n\n⏰ Muddat: {t['deadline']}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📤 Topshirish", callback_data=f"submit:{t['id']}")]]
    )
    await cb.message.answer(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("submit:"))
async def start_submit(cb: CallbackQuery, state: FSMContext):
    if is_admin(cb.from_user.id):
        await cb.answer("O'qituvchi vazifa topshira olmaydi", show_alert=True)
        return
    task_id = int(cb.data.split(":")[1])
    t = db.get_task(task_id)
    if not t or not t["active"]:
        await cb.answer("Bu vazifa yopilgan.", show_alert=True)
        return
    prev = db.get_user_submission(task_id, cb.from_user.id)
    if prev and prev["status"] == "pending":
        await cb.answer("Ishingiz tekshirilmoqda, kuting.", show_alert=True)
        return
    if prev and prev["status"] == "graded":
        await cb.answer(f"Siz allaqachon topshirgansiz. Baho: {prev['grade']}", show_alert=True)
        return
    await state.set_state(Submit.waiting)
    await state.update_data(task_id=task_id)
    await cb.message.answer(
        f"«{t['title']}» uchun javobingizni yuboring (matn, rasm yoki fayl).\nBekor qilish: /cancel"
    )
    await cb.answer()


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.")


@router.message(Submit.waiting, F.text | F.photo | F.document)
async def receive_submission(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    task_id = data["task_id"]

    if message.photo:
        ctype, file_id, text = "photo", message.photo[-1].file_id, message.caption
    elif message.document:
        ctype, file_id, text = "document", message.document.file_id, message.caption
    else:
        ctype, file_id, text = "text", None, message.text

    u = message.from_user
    db.upsert_user(u.id, u.full_name, u.username)
    sub_id = db.add_submission(task_id, u.id, ctype, text, file_id)
    await state.clear()
    await message.answer("✅ Vazifa qabul qilindi. O'qituvchi tekshirgach xabar beraman.")

    for admin_id in ADMIN_IDS:
        try:
            await send_submission(bot, admin_id, sub_id)
        except Exception:
            logging.exception("Adminga yuborib bo'lmadi: %s", admin_id)


@router.message(Submit.waiting)
async def submission_wrong_type(message: Message):
    await message.answer("Iltimos, matn, rasm yoki fayl yuboring (yoki /cancel).")


# ======================= STUDENT: natijalar =======================
@router.message(F.text == BTN_RESULTS)
@router.message(Command("results"))
async def my_results(message: Message):
    rows = db.user_results(message.from_user.id)
    if not rows:
        await message.answer("Hali topshirilgan vazifa yo'q.")
        return
    status_txt = {"pending": "⏳ tekshirilmoqda", "redo": "🔁 qayta topshiring"}
    lines = []
    for r in rows:
        st = f"✅ baho: {r['grade']}" if r["status"] == "graded" else status_txt[r["status"]]
        line = f"• {r['task_title']} – {st}"
        if r["comment"]:
            line += f"\n   💬 {r['comment']}"
        lines.append(line)
    await message.answer("\n".join(lines))


# ======================= main =======================
async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN topilmadi. .env faylini to'ldiring.")
    if not ADMIN_IDS:
        logging.warning("ADMIN_IDS bo'sh – o'qituvchi aniqlanmaydi!")
    db.init_db()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
