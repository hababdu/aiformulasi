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
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

import db
import keepalive
import persist

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
# O'quvchilar guruhining ID raqami (-100... bilan boshlanadi). Bo'sh bo'lsa, guruh ishlatilmaydi.
GROUP_ID = int(os.getenv("GROUP_ID", "0") or 0)

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


# ======================= GURUH: o'quvchilarni yig'ish =======================
# Telegram botlarga guruh a'zolarining ro'yxatini bermaydi, shuning uchun a'zolar
# kirish/chiqish hodisalaridan, guruhdagi xabarlardan va /start paytidagi tekshiruvdan yig'iladi.
MEMBER_STATUSES = {"creator", "administrator", "member"}


def _in_chat(cm) -> bool:
    return cm.status in MEMBER_STATUSES or (
        cm.status == "restricted" and getattr(cm, "is_member", False)
    )


def _is_student(u) -> bool:
    return bool(u) and not u.is_bot and not is_admin(u.id)


# Guruh handlerlari boshqalardan oldin turishi kerak.
@router.chat_member(F.chat.id == GROUP_ID)
async def group_member_update(event: ChatMemberUpdated):
    u = event.new_chat_member.user
    if _is_student(u):
        db.set_in_group(u.id, u.full_name, u.username, _in_chat(event.new_chat_member))


@router.message(F.chat.id == GROUP_ID)
async def group_message(message: Message):
    if _is_student(message.from_user):
        u = message.from_user
        db.set_in_group(u.id, u.full_name, u.username, True)
    for m in message.new_chat_members or []:
        if _is_student(m):
            db.set_in_group(m.id, m.full_name, m.username, True)
    left = message.left_chat_member
    if _is_student(left):
        db.set_in_group(left.id, left.full_name, left.username, False)


async def refresh_membership(bot: Bot, u) -> None:
    """/start bosgan foydalanuvchining guruh a'zoligini Telegramdan so'rab tekshiradi."""
    if not GROUP_ID or not _is_student(u):
        return
    try:
        cm = await bot.get_chat_member(GROUP_ID, u.id)
        db.set_in_group(u.id, u.full_name, u.username, _in_chat(cm))
    except Exception:
        logging.warning("Guruh a'zoligini tekshirib bo'lmadi: %s", u.id)


@router.message(Command("students"), F.func(lambda m: is_admin(m.from_user.id)))
async def admin_students(message: Message, bot: Bot):
    if not GROUP_ID:
        await message.answer("GROUP_ID sozlanmagan.")
        return
    rows = db.group_members()
    try:
        total = await bot.get_chat_member_count(GROUP_ID)
    except Exception:
        total = None
    started = sum(1 for r in rows if r["started"])
    head = f"👥 Ro'yxatda: {len(rows)} ta o'quvchi (botni ishga tushirgan: {started})"
    if total is not None:
        head += f"\nGuruhda jami: {total} ta a'zo (admin va botlar bilan)"
    head += (
        "\nGuruhda yozmagan va botni ishga tushirmagan a'zolar ro'yxatda ko'rinmaydi: "
        "Telegram botga a'zolar ro'yxatini bermaydi."
    )
    lines = [
        f"{i}. {r['full_name']}"
        + (f" (@{r['username']})" if r["username"] else "")
        + ("" if r["started"] else " ⚠️ botni ishga tushirmagan")
        for i, r in enumerate(rows, 1)
    ]
    text = head + ("\n\n" + "\n".join(lines) if lines else "")
    for i in range(0, len(text), 4000):
        await message.answer(text[i : i + 4000])


# ======================= /start =======================
@router.message(CommandStart())
async def start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    u = message.from_user
    db.upsert_user(u.id, u.full_name, u.username, started=True)
    await refresh_membership(bot, u)
    if is_admin(u.id):
        await message.answer(
            "Salom, o'qituvchi! 👨‍🏫\n\n"
            "/newtask – yangi vazifa berish\n"
            "/tasks – faol vazifalar\n"
            "/pending – tekshirilmagan ishlar\n"
            "/close <id> – vazifani yopish\n"
            "/students – guruh a'zolari ro'yxati"
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
    for uid in db.broadcast_ids(bool(GROUP_ID)):
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
    db.upsert_user(u.id, u.full_name, u.username, started=True)
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
    # HTTP server avval ishga tushadi: Render portni tezda topishi kerak.
    runner = await keepalive.start_server()
    bot = Bot(BOT_TOKEN)
    await persist.restore(bot)  # kanaldagi snapshotdan bazani tiklaydi
    db.init_db()
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    background = [
        asyncio.create_task(keepalive.ping_loop()),
        asyncio.create_task(persist.autosave_loop(bot)),
    ]
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for t in background:
            t.cancel()
        if db.is_dirty():
            try:
                await persist.push(bot)  # to'xtashdan oldin oxirgi o'zgarishlarni saqlash
            except Exception:
                logging.exception("Yakuniy snapshotni saqlab bo'lmadi")
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
