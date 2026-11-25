"""Bazani yopiq Telegram kanalida saqlash.

Render bepul rejasida fayl tizimi vaqtinchalik: qayta ishga tushganda homework.db
yo'qoladi. Shu sababli baza faylining nusxasi (snapshot) yopiq kanalga hujjat sifatida
yuboriladi va pin qilinadi. Bot ishga tushganda pin qilingan hujjatni yuklab olib,
bazani tiklaydi. Keyingi saqlashlarda o'sha xabar ichidagi fayl almashtiriladi
(yangi xabar yaratilmaydi).

Botga kanalda admin huquqi kerak: xabar yuborish, xabarni tahrirlash, xabarni pin qilish.
"""
import asyncio
import logging
import os
import sqlite3
import tempfile
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import FSInputFile, InputMediaDocument

import db

CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID", "0") or 0)
CHECK_EVERY = 10  # soniya: o'zgarish bor-yo'qligini tekshirish
MIN_GAP = 30      # soniya: ikki saqlash orasidagi eng kam vaqt

_msg_id: int | None = None


def enabled() -> bool:
    return bool(CHANNEL_ID)


def _valid(path: str) -> bool:
    try:
        con = sqlite3.connect(path)
        try:
            return con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except sqlite3.Error:
        return False


async def restore(bot: Bot) -> None:
    """Pin qilingan snapshotni yuklab, bo'sh joyga bazani tiklaydi."""
    global _msg_id
    if not enabled():
        logging.warning("STORAGE_CHANNEL_ID yo'q: baza faqat lokal faylda saqlanadi")
        return
    try:
        chat = await bot.get_chat(CHANNEL_ID)
    except TelegramAPIError as e:
        # Bu yerda davom etsak, bo'sh baza kanaldagi eski nusxani bosib yuborishi mumkin.
        raise SystemExit(
            f"Saqlash kanaliga kirib bo'lmadi ({e}). Bot kanalda admin ekanini va "
            "STORAGE_CHANNEL_ID to'g'riligini tekshiring."
        )
    pm = chat.pinned_message
    if not pm or not pm.document:
        logging.info("Kanalda snapshot yo'q: bo'sh baza bilan boshlanadi")
        return
    _msg_id = pm.message_id
    if os.path.exists(db.DB_PATH):
        logging.info("Lokal baza mavjud: tiklash o'tkazib yuborildi")
        return
    folder = os.path.dirname(db.DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = db.DB_PATH + ".restore"
    await bot.download(pm.document.file_id, destination=tmp)
    if _valid(tmp):
        os.replace(tmp, db.DB_PATH)
        logging.info("Baza kanaldagi snapshotdan tiklandi")
    else:
        os.remove(tmp)
        raise SystemExit("Kanaldagi snapshot buzilgan, avtomatik tiklab bo'lmadi.")


def _make_copy() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    src = sqlite3.connect(db.DB_PATH)
    dst = sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return path


async def push(bot: Bot) -> None:
    """Hozirgi bazani kanalga saqlaydi."""
    global _msg_id
    if not enabled():
        return
    path = await asyncio.to_thread(_make_copy)
    caption = "DB snapshot " + time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    try:
        if _msg_id:
            try:
                await bot.edit_message_media(
                    InputMediaDocument(
                        media=FSInputFile(path, filename="homework.db"), caption=caption
                    ),
                    chat_id=CHANNEL_ID,
                    message_id=_msg_id,
                )
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return
                logging.warning("Snapshotni tahrirlab bo'lmadi (%s): yangisi yuboriladi", e)
                _msg_id = None
        msg = await bot.send_document(
            CHANNEL_ID,
            FSInputFile(path, filename="homework.db"),
            caption=caption,
            disable_notification=True,
        )
        await bot.pin_chat_message(CHANNEL_ID, msg.message_id, disable_notification=True)
        _msg_id = msg.message_id
    finally:
        os.remove(path)


async def autosave_loop(bot: Bot) -> None:
    """Baza o'zgargan bo'lsa, har ~30 soniyada kanalga saqlaydi."""
    if not enabled():
        return
    last = 0.0
    while True:
        await asyncio.sleep(CHECK_EVERY)
        if db.is_dirty() and time.monotonic() - last >= MIN_GAP:
            db.clear_dirty()
            try:
                await push(bot)
                last = time.monotonic()
            except Exception:
                logging.exception("Snapshotni kanalga saqlab bo'lmadi")
                db.mark_dirty()
