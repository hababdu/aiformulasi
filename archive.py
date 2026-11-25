"""Yopiq kanalga doimiy zahira arxivi.

Har bir muhim hodisa (yangi vazifa, topshiriq, baho, o'quvchining guruhga kirishi/chiqishi)
kanalga alohida xabar bo'lib yoziladi va u yerda to'planib boradi. Bundan tashqari, o'zgarish
bo'lsa, soatiga ko'pi bilan bir marta CSV hisobot (o'quvchilar, vazifalar, topshiriqlar va
ballar) yuboriladi. `homework.db` ning joriy nusxasi esa persist.py orqali pin qilingan
xabarda turadi.
"""
import asyncio
import csv
import logging
import os
import shutil
import tempfile
import time

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaDocument

import config as cfg
import db

REPORT_GAP = 3600   # soniya: CSV hisobotlar orasidagi eng kam vaqt
REPORT_CHECK = 60   # soniya: o'zgarish bor-yo'qligini tekshirish
_bg: set = set()


def fire(coro) -> None:
    """Arxiv yozishni orqa fonda bajaradi: asosiy ish kutib qolmaydi va xatosi uni to'xtatmaydi."""
    task = asyncio.create_task(_safe(coro))
    _bg.add(task)
    task.add_done_callback(_bg.discard)


async def _safe(coro) -> None:
    try:
        await coro
    except Exception:
        logging.exception("Kanalga arxiv yozib bo'lmadi")


def _on() -> bool:
    return bool(cfg.channel_id)


def _who(full_name: str, username: str | None) -> str:
    return full_name + (f" (@{username})" if username else "")


async def log_text(bot: Bot, text: str) -> None:
    if _on():
        await bot.send_message(cfg.channel_id, text[:4096], disable_notification=True)


async def log_task(bot: Bot, task_id: int) -> None:
    t = db.get_task(task_id)
    if not t or not _on():
        return
    text = f"📢 Vazifa #{t['id']}: {t['title']}\n\n{t['description'] or ''}"
    if t["deadline"]:
        text += f"\n\n⏰ Muddat: {t['deadline']}"
    await log_text(bot, text)


async def log_submission(bot: Bot, sub_id: int) -> None:
    s = db.get_submission(sub_id)
    if not s or not _on():
        return
    header = (
        f"📥 Topshiriq #{s['id']} | vazifa: {s['task_title']}\n"
        f"👤 {_who(s['full_name'], s['username'])} | ID {s['user_id']}\n"
    )
    body = s["text"] or ""
    if s["content_type"] == "photo":
        await bot.send_photo(
            cfg.channel_id, s["file_id"], caption=(header + body)[:1024], disable_notification=True
        )
    elif s["content_type"] == "document":
        await bot.send_document(
            cfg.channel_id, s["file_id"], caption=(header + body)[:1024], disable_notification=True
        )
    else:
        await log_text(bot, header + "\n" + body)


async def log_review(bot: Bot, sub_id: int) -> None:
    s = db.get_submission(sub_id)
    if not s or not _on():
        return
    status = f"✅ Baho: {s['grade']}" if s["status"] == "graded" else "🔁 Qayta topshirish so'raldi"
    text = f"{status}\n📝 Topshiriq #{s['id']} | {s['task_title']}\n👤 {_who(s['full_name'], s['username'])}"
    if s["comment"]:
        text += f"\n💬 {s['comment']}"
    await log_text(bot, text)


async def log_student(bot: Bot, full_name: str, username: str | None, joined: bool) -> None:
    prefix = "➕ O'quvchi ro'yxatga qo'shildi: " if joined else "➖ O'quvchi guruhdan chiqdi: "
    await log_text(bot, prefix + _who(full_name, username))


# ---------- CSV hisobot ----------
def _write_csv(path: str, header: list[str], rows: list[tuple]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel to'g'ri ochadi
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


async def send_report(bot: Bot, chat_id: int, note: str | None = None) -> None:
    """O'quvchilar, vazifalar va topshiriqlar+ballar CSV fayllarini chatga yuboradi."""
    data = await asyncio.to_thread(db.export_all)
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    caption = f"🗂 Zahira nusxa {stamp}" + (f" ({note})" if note else "")
    specs = [
        ("oquvchilar.csv", ["id", "ism", "username", "guruhda", "botni_ishga_tushirgan"], data["students"]),
        ("vazifalar.csv", ["id", "nom", "tavsif", "muddat", "faol", "yaratilgan"], data["tasks"]),
        (
            "topshiriqlar_ballar.csv",
            ["id", "vazifa", "oquvchi", "username", "turi", "matn", "holat", "baho", "izoh", "vaqt"],
            data["submissions"],
        ),
    ]
    folder = tempfile.mkdtemp()
    try:
        media = []
        for i, (name, header, rows) in enumerate(specs):
            path = os.path.join(folder, name)
            _write_csv(path, header, rows)
            media.append(
                InputMediaDocument(
                    media=FSInputFile(path, filename=name), caption=caption if i == 0 else None
                )
            )
        await bot.send_media_group(chat_id, media, disable_notification=True)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


async def report_loop(bot: Bot) -> None:
    """Baza o'zgargan bo'lsa, soatiga ko'pi bilan bir marta CSV hisobotni kanalga yuboradi."""
    last = None
    while True:
        await asyncio.sleep(REPORT_CHECK)
        if not _on() or not db.report_is_dirty():
            continue
        if last is not None and time.monotonic() - last < REPORT_GAP:
            continue
        db.clear_report_dirty()
        try:
            await send_report(bot, cfg.channel_id)
            last = time.monotonic()
        except Exception:
            logging.exception("CSV hisobotni kanalga yuborib bo'lmadi")
            db.mark_report_dirty()
