"""O'qituvchi statistikasi: umumiy ko'rinish, vazifalar, reyting va topshirmaganlar."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config as cfg
import db
from ui import BTN_STATS

router = Router()
MAX_LEN = 3900
MEDALS = ["🥇", "🥈", "🥉"]


def bar(done: int, total: int, width: int = 10) -> str:
    """▓▓▓▓░░░░░░ 40%"""
    pct = round(100 * done / total) if total else 0
    filled = round(width * pct / 100)
    return "▓" * filled + "░" * (width - filled) + f" {pct}%"


def fmt_avg(v) -> str:
    return f"{v:.1f}" if v is not None else "–"


def name(st: dict) -> str:
    return st["full_name"] + (f" (@{st['username']})" if st["username"] else "")


def _cut(text: str) -> str:
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 20].rstrip() + "\n…(davomi qisqartirildi)"


def nav(current: str) -> InlineKeyboardMarkup:
    tabs = [
        ("home", "📊 Umumiy"),
        ("tasks", "📚 Vazifalar"),
        ("top", "🏆 Reyting"),
        ("missing", "⚠️ Topshirmagan"),
    ]
    row1 = [
        InlineKeyboardButton(text=("• " + t if k == current else t), callback_data=f"st:{k}")
        for k, t in tabs[:2]
    ]
    row2 = [
        InlineKeyboardButton(text=("• " + t if k == current else t), callback_data=f"st:{k}")
        for k, t in tabs[2:]
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[row1, row2, [InlineKeyboardButton(text="🔄 Yangilash", callback_data=f"st:{current}")]]
    )


def view_home(snap: dict) -> str:
    students, tasks, subs = snap["students"], snap["tasks"], snap["subs"]
    active = [t for t in tasks if t["active"]]
    if not students and not tasks:
        return "📊 Statistika\n\nHali ma'lumot yo'q: o'quvchilar botga /start bosganida va vazifa berilganda to'ladi."
    pending = sum(1 for s in subs if s["status"] == "pending")
    graded = sum(1 for s in subs if s["status"] == "graded")
    redo = sum(1 for s in subs if s["status"] == "redo")
    # Topshirish ko'rsatkichi: faol vazifalar bo'yicha (o'quvchi × vazifa) juftliklaridan nechtasi topshirilgan
    active_ids = {t["id"] for t in active}
    done = sum(1 for s in subs if s["task_id"] in active_ids)
    possible = len(students) * len(active)
    lines = [
        "📊 Statistika",
        "",
        f"👥 O'quvchilar: {len(students)}",
        f"📚 Vazifalar: {len(active)} faol, jami {len(tasks)}",
        "",
        "Faol vazifalar topshirilishi",
        bar(done, possible) + f"  ({done}/{possible})",
        "",
        "Topshirilgan ishlar",
        f"✅ Tekshirilgan: {graded}",
        f"⏳ Tekshirilmagan: {pending}",
        f"🔁 Qayta topshirish: {redo}",
        "",
        f"⭐ O'rtacha baho: {fmt_avg(snap['avg'])}",
    ]
    if pending:
        lines += ["", f"👉 {pending} ta ish tekshirishni kutmoqda («📥 Tekshirilmagan»)"]
    return "\n".join(lines)


def view_tasks(snap: dict) -> str:
    tasks, n = snap["tasks"][:10], len(snap["students"])
    if not tasks:
        return "📚 Vazifalar bo'yicha\n\nHali vazifa yo'q."
    out = ["📚 Vazifalar bo'yicha (oxirgi 10 ta)", f"Foiz = o'quvchilarning nechtasi topshirgani ({n} ta o'quvchidan)", ""]
    for t in tasks:
        extra = []
        if t["avg"] is not None:
            extra.append(f"⭐ {fmt_avg(t['avg'])}")
        if t["pending"]:
            extra.append(f"⏳ {t['pending']} tekshirilmagan")
        if t["redo"]:
            extra.append(f"🔁 {t['redo']} qayta")
        out.append(f"{'🟢' if t['active'] else '🔒'} #{t['id']} {t['title']}")
        out.append(f"{bar(t['submitted'], n)}  {t['submitted']}/{n}" + ("  ·  " + "  ·  ".join(extra) if extra else ""))
        out.append("")
    return _cut("\n".join(out).rstrip())


def view_top(snap: dict) -> str:
    ranked = [s for s in snap["students"] if s["avg"] is not None]
    if not ranked:
        return "🏆 Reyting\n\nHali baholangan ish yo'q."
    ranked.sort(key=lambda s: (-s["avg"], -s["submitted"], s["full_name"]))
    out = ["🏆 Reyting (o'rtacha baho bo'yicha)", ""]
    for i, s in enumerate(ranked[:15], 1):
        mark = MEDALS[i - 1] if i <= 3 else f"{i}."
        out.append(f"{mark} {s['full_name']}  ⭐ {fmt_avg(s['avg'])}  ·  {s['submitted']} ta ish")
    rest = len(ranked) - 15
    if rest > 0:
        out.append(f"… va yana {rest} ta o'quvchi")
    nograde = len(snap["students"]) - len(ranked)
    if nograde:
        out += ["", f"Hali bahosi yo'q: {nograde} ta o'quvchi"]
    return _cut("\n".join(out))


def view_missing(snap: dict) -> str:
    active = [t for t in snap["tasks"] if t["active"]]
    if not active:
        return "⚠️ Topshirmaganlar\n\nFaol vazifa yo'q."
    out = ["⚠️ Topshirmaganlar (faol vazifalar)", ""]
    for t in active:
        miss = t["missing"]
        if not miss:
            out.append(f"#{t['id']} {t['title']}: hamma topshirgan ✅")
        else:
            out.append(f"#{t['id']} {t['title']}: {len(miss)} ta")
            out += [f"  • {name(s)}" for s in miss[:20]]
            if len(miss) > 20:
                out.append(f"  … va yana {len(miss) - 20} ta")
        out.append("")
    return _cut("\n".join(out).rstrip())


VIEWS = {"home": view_home, "tasks": view_tasks, "top": view_top, "missing": view_missing}


def render(kind: str) -> tuple[str, InlineKeyboardMarkup]:
    kind = kind if kind in VIEWS else "home"
    return VIEWS[kind](db.stats_snapshot(cfg.ADMIN_IDS)), nav(kind)


@router.message(Command("stats"), F.func(lambda m: cfg.is_admin(m.from_user.id)))
@router.message(F.text == BTN_STATS, F.func(lambda m: cfg.is_admin(m.from_user.id)))
async def admin_stats(message: Message, state: FSMContext):
    await state.clear()
    text, kb = render("home")
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("st:"))
async def stats_tab(cb: CallbackQuery):
    if not cfg.is_admin(cb.from_user.id):
        await cb.answer("Faqat o'qituvchi uchun", show_alert=True)
        return
    text, kb = render(cb.data.split(":", 1)[1])
    try:
        await cb.message.edit_text(text, reply_markup=kb)
        await cb.answer()
    except Exception:  # matn o'zgarmagan bo'lsa Telegram xato qaytaradi
        await cb.answer("Yangilandi, o'zgarish yo'q")
