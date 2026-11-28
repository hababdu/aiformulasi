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

import admin_setup
import archive
import config as cfg
import db
import keepalive
import persist
import stats
from ui import (
    BTN_ADMIN_TASKS,
    BTN_NEWTASK,
    BTN_PENDING,
    BTN_RESULTS,
    BTN_STUDENTS,
    BTN_TASKS,
    MENU_BUTTONS,
    NOT_CMD,
    NOT_MENU,
    TEXT_OR_SKIP,
    admin_menu,
    cancel_kb,
    student_menu,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = cfg.ADMIN_IDS

router = Router()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


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


def is_group(chat_id: int) -> bool:
    """O'quvchilar guruhi admin tomonidan botning o'zida ulanadi (cfg.group_id)."""
    return bool(cfg.group_id) and chat_id == cfg.group_id


async def _track(bot: Bot, u, in_group: bool) -> None:
    """A'zolik holatini yozadi; o'zgargan bo'lsa, kanalga arxiv xabari yuboradi."""
    if _is_student(u) and db.set_in_group(u.id, u.full_name, u.username, in_group):
        archive.fire(archive.log_student(bot, u.full_name, u.username, in_group))


# Guruh handlerlari boshqalardan oldin turishi kerak.
@router.chat_member(F.func(lambda e: is_group(e.chat.id)))
async def group_member_update(event: ChatMemberUpdated, bot: Bot):
    await _track(bot, event.new_chat_member.user, _in_chat(event.new_chat_member))


@router.message(F.func(lambda m: is_group(m.chat.id)))
async def group_message(message: Message, bot: Bot):
    await _track(bot, message.from_user, True)
    for m in message.new_chat_members or []:
        await _track(bot, m, True)
    await _track(bot, message.left_chat_member, False)


async def refresh_membership(bot: Bot, u) -> None:
    """/start bosgan foydalanuvchining guruh a'zoligini Telegramdan so'rab tekshiradi."""
    if not cfg.group_id or not _is_student(u):
        return
    try:
        cm = await bot.get_chat_member(cfg.group_id, u.id)
    except Exception:
        logging.warning("Guruh a'zoligini tekshirib bo'lmadi: %s", u.id)
        return
    await _track(bot, u, _in_chat(cm))


@router.message(Command("students"), F.func(lambda m: is_admin(m.from_user.id)))
@router.message(F.text == BTN_STUDENTS, F.func(lambda m: is_admin(m.from_user.id)))
async def admin_students(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    if not cfg.group_id:
        await message.answer("Guruh ulanmagan. «⚙️ Sozlamalar» tugmasi orqali guruhni ulang.")
        return
    rows = db.group_members()
    try:
        total = await bot.get_chat_member_count(cfg.group_id)
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
            "Quyidagi tugmalardan foydalaning. Birinchi marta bo'lsa, «⚙️ Sozlamalar» "
            "orqali yopiq kanal va o'quvchilar guruhini ulang.",
            reply_markup=admin_menu(),
        )
    else:
        await message.answer(
            f"Salom, {u.first_name}! 👋\n"
            "Bu yerda vazifalarni topshirishingiz va natijalarni ko'rishingiz mumkin.",
            reply_markup=student_menu(),
        )


# ======================= TEACHER: yangi vazifa =======================
@router.message(Command("newtask"), F.func(lambda m: is_admin(m.from_user.id)))
@router.message(F.text == BTN_NEWTASK, F.func(lambda m: is_admin(m.from_user.id)))
async def newtask_start(message: Message, state: FSMContext):
    await state.set_state(NewTask.title)
    await message.answer("Vazifa nomini yozing:", reply_markup=cancel_kb())


@router.message(NewTask.title, F.text, NOT_MENU, NOT_CMD)
async def newtask_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(NewTask.description)
    await message.answer("Vazifa tavsifini yozing (nima qilish kerak):", reply_markup=cancel_kb())


@router.message(NewTask.description, F.text, NOT_MENU, NOT_CMD)
async def newtask_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(NewTask.deadline)
    await message.answer(
        "Topshirish muddatini yozing (masalan: 12-noyabr 23:59) yoki tugmani bosing:",
        reply_markup=cancel_kb("⏭ Muddatsiz"),
    )


@router.message(NewTask.deadline, F.text, NOT_MENU, TEXT_OR_SKIP)
async def newtask_deadline(message: Message, state: FSMContext, bot: Bot):
    deadline = None if message.text.strip() == "/skip" else message.text.strip()
    await finish_newtask(bot, message.chat.id, state, deadline)


@router.callback_query(F.data == "skip", NewTask.deadline)
async def newtask_deadline_skip(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await cb.answer()
    await finish_newtask(bot, cb.message.chat.id, state, None)


async def finish_newtask(bot: Bot, chat_id: int, state: FSMContext, deadline: str | None):
    data = await state.get_data()
    await state.clear()
    task_id = db.add_task(data["title"], data["description"], deadline)
    archive.fire(archive.log_task(bot, task_id))
    await bot.send_message(chat_id, f"✅ Vazifa #{task_id} yaratildi. O'quvchilarga yuborilmoqda...")

    text = f"📢 Yangi vazifa!\n\n{data['title']}\n\n{data['description']}"
    if deadline:
        text += f"\n\n⏰ Muddat: {deadline}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📤 Topshirish", callback_data=f"submit:{task_id}")]]
    )
    sent = 0
    for uid in db.broadcast_ids(bool(cfg.group_id)):
        if is_admin(uid):
            continue
        try:
            await bot.send_message(uid, text, reply_markup=kb)
            sent += 1
        except Exception:
            pass
    await bot.send_message(chat_id, f"📨 {sent} ta o'quvchiga yuborildi.")


# ======================= TEACHER: ro'yxatlar =======================
def tasks_view():
    """Faol vazifalar matni va har biri uchun «Yopish» tugmasi."""
    tasks = db.active_tasks()
    if not tasks:
        return "Faol vazifalar yo'q.", None
    pend = db.pending_count_by_task()
    lines = [
        f"#{t['id']} – {t['title']} (tekshirilmagan: {pend.get(t['id'], 0)})"
        for t in tasks
    ]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔒 Yopish: #{t['id']} {t['title'][:30]}",
                    callback_data=f"close:{t['id']}",
                )
            ]
            for t in tasks
        ]
    )
    return "\n".join(lines), kb


@router.message(Command("tasks"), F.func(lambda m: is_admin(m.from_user.id)))
@router.message(F.text == BTN_ADMIN_TASKS, F.func(lambda m: is_admin(m.from_user.id)))
async def admin_tasks(message: Message, state: FSMContext):
    await state.clear()
    text, kb = tasks_view()
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("close:"))
async def on_close(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("Faqat o'qituvchi uchun", show_alert=True)
        return
    ok = db.close_task(int(cb.data.split(":")[1]))
    await cb.answer("✅ Vazifa yopildi." if ok else "Bunday vazifa topilmadi.")
    text, kb = tasks_view()
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass


@router.message(Command("close"), F.func(lambda m: is_admin(m.from_user.id)))
async def admin_close(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Foydalanish: /close <vazifa_id>")
        return
    ok = db.close_task(int(parts[1]))
    await message.answer("✅ Vazifa yopildi." if ok else "Bunday vazifa topilmadi.")


def review_keyboard(sub_id: int) -> InlineKeyboardMarkup:
    def row(nums):
        return [InlineKeyboardButton(text=str(g), callback_data=f"grade:{sub_id}:{g}") for g in nums]

    redo = [InlineKeyboardButton(text="🔁 Qayta topshirsin", callback_data=f"grade:{sub_id}:redo")]
    return InlineKeyboardMarkup(inline_keyboard=[row(range(10, 5, -1)), row(range(5, 0, -1)), redo])


async def send_submission(bot: Bot, chat_id: int, sub_id: int, left: int = 0):
    s = db.get_submission(sub_id)
    if not s:
        return
    who = s["full_name"] + (f" (@{s['username']})" if s["username"] else "")
    header = f"📝 #{s['id']} | {s['task_title']}\n👤 {who}\n"
    if left:
        header += f"📥 Navbatda yana {left} ta\n"
    body = s["text"] or ""
    kb = review_keyboard(s["id"])
    if s["content_type"] == "photo":
        await bot.send_photo(chat_id, s["file_id"], caption=(header + body)[:1024], reply_markup=kb)
    elif s["content_type"] == "document":
        await bot.send_document(chat_id, s["file_id"], caption=(header + body)[:1024], reply_markup=kb)
    else:
        await bot.send_message(chat_id, (header + "\n" + body)[:4096], reply_markup=kb)


@router.message(Command("pending"), F.func(lambda m: is_admin(m.from_user.id)))
@router.message(F.text == BTN_PENDING, F.func(lambda m: is_admin(m.from_user.id)))
async def admin_pending(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    await send_next_pending(bot, message.chat.id)


async def send_next_pending(bot: Bot, chat_id: int, after_review: bool = False):
    """Tekshirilmagan ishlardan faqat bittasini yuboradi; keyingisi shu ish baholangach chiqadi."""
    rows = db.pending_submissions()
    if not rows:
        await bot.send_message(
            chat_id, "Hammasi tekshirildi 🎉" if after_review else "Tekshirilmagan ishlar yo'q 🎉"
        )
        return
    await send_submission(bot, chat_id, rows[0]["id"], left=len(rows) - 1)


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
    if grade == "redo":
        # Qaytarilgan ishda izoh majburiy: o'quvchi nimani tuzatishini bilishi kerak.
        await cb.message.answer(
            "🔁 Qayta topshirish. O'quvchiga nimani tuzatish kerakligini yozing (izoh o'quvchiga yuboriladi):",
            reply_markup=cancel_kb(),
        )
    else:
        await cb.message.answer(
            f"Baho: {grade}/10. Izoh yozing yoki tugmani bosing:", reply_markup=cancel_kb("⏭ Izohsiz")
        )
    await cb.answer()


@router.message(Review.comment, F.text, NOT_MENU, TEXT_OR_SKIP)
async def on_comment(message: Message, state: FSMContext, bot: Bot):
    comment = None if message.text.strip() == "/skip" else message.text.strip()
    if comment is None and (await state.get_data()).get("grade") == "redo":
        await message.answer("Qaytarilgan ishga izoh yozing: o'quvchi nimani tuzatishini bilishi kerak.", reply_markup=cancel_kb())
        return
    await finish_review(bot, message.chat.id, state, comment)


@router.callback_query(F.data == "skip", Review.comment)
async def on_comment_skip(cb: CallbackQuery, state: FSMContext, bot: Bot):
    if (await state.get_data()).get("grade") == "redo":
        await cb.answer("Qaytarilgan ishga izoh yozish kerak.", show_alert=True)
        return
    await cb.answer()
    await finish_review(bot, cb.message.chat.id, state, None)


async def finish_review(bot: Bot, chat_id: int, state: FSMContext, comment: str | None):
    data = await state.get_data()
    await state.clear()
    s = db.get_submission(data["sub_id"])
    if not s or s["status"] != "pending":
        await bot.send_message(chat_id, "Bu ish allaqachon tekshirilgan.")
        return

    grade = data["grade"]
    if grade == "redo":
        db.review_submission(s["id"], "redo", None, comment)
        text = f"🔁 «{s['task_title']}» vazifangizni qayta topshiring."
        if comment:
            text += f"\n💬 O'qituvchi izohi: {comment}"
        redo_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📤 Qayta topshirish", callback_data=f"submit:{s['task_id']}")]]
        )
    else:
        db.review_submission(s["id"], "graded", grade, comment)
        text = f"✅ «{s['task_title']}» vazifangiz tekshirildi.\nBaho: {grade}/10"
        redo_kb = None
    if comment and grade != "redo":
        text += f"\n💬 Izoh: {comment}"
    archive.fire(archive.log_review(bot, s["id"]))

    try:
        await bot.send_message(s["user_id"], text, reply_markup=redo_kb)
        await bot.send_message(chat_id, "Natija o'quvchiga yuborildi ✅")
    except Exception:
        await bot.send_message(chat_id, "Saqlandi, lekin o'quvchiga xabar yuborib bo'lmadi.")
    await send_next_pending(bot, chat_id, after_review=True)  # keyingi ish


# ======================= STUDENT: vazifalar =======================
@router.message(F.text == BTN_TASKS)
async def student_tasks(message: Message, state: FSMContext):
    await state.clear()
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
        f"«{t['title']}» uchun javobingizni yuboring (matn, rasm yoki fayl).",
        reply_markup=cancel_kb(),
    )
    await cb.answer()


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.")


@router.callback_query(F.data == "cancel")
async def cancel_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("Bekor qilindi")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@router.message(Submit.waiting, (F.text & NOT_MENU) | F.photo | F.document)
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
    archive.fire(archive.log_submission(bot, sub_id))
    await state.clear()
    await message.answer("✅ Vazifa qabul qilindi. O'qituvchi tekshirgach xabar beraman.")
    # O'qituvchiga o'zi yuborilmaydi: ishlar «📥 Tekshirilmagan» tugmasi bosilganda ko'rsatiladi.


@router.message(Submit.waiting, F.func(lambda m: (m.text or "") not in MENU_BUTTONS))
async def submission_wrong_type(message: Message):
    await message.answer(
        "Iltimos, matn, rasm yoki fayl yuboring.", reply_markup=cancel_kb()
    )


# ======================= STUDENT: natijalar =======================
@router.message(F.text == BTN_RESULTS)
@router.message(Command("results"))
async def my_results(message: Message, state: FSMContext):
    await state.clear()
    rows = db.user_results(message.from_user.id)
    if not rows:
        await message.answer("Hali topshirilgan vazifa yo'q.")
        return
    sm = db.student_summary(message.from_user.id)
    head = f"📊 Topshirgan ishlaringiz: {sm['submitted']}/{sm['total_tasks']}  ·  ⭐ o'rtacha baho: " + (
        f"{sm['avg']:.1f}" if sm["avg"] is not None else "–"
    )
    if sm["active_missing"]:
        head += "\n⚠️ Hali topshirilmagan: " + ", ".join(sm["active_missing"][:5])
    head += "\n\n"
    status_txt = {"pending": "⏳ tekshirilmoqda", "redo": "🔁 qayta topshiring"}
    lines = []
    for r in rows:
        st = f"✅ baho: {r['grade']}/10" if r["status"] == "graded" else status_txt[r["status"]]
        line = f"• {r['task_title']} – {st}"
        if r["comment"]:
            line += f"\n   💬 {r['comment']}"
        lines.append(line)
    await message.answer(head + "\n".join(lines))


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
    try:
        await bot.delete_my_commands()  # buyruqlar o'rniga tugmalar ishlatiladi
    except Exception:
        logging.warning("Buyruqlar ro'yxatini tozalab bo'lmadi")
    await cfg.load(bot)  # ulangan kanal/guruh ID lari admin chatidagi pin qilingan xabardan
    await persist.restore(bot)  # kanaldagi snapshotdan bazani tiklaydi
    db.init_db()
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_setup.router)
    dp.include_router(stats.router)
    dp.include_router(router)
    background = [
        asyncio.create_task(keepalive.ping_loop()),
        asyncio.create_task(persist.autosave_loop(bot)),
        asyncio.create_task(archive.report_loop(bot)),
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
