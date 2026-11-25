"""Bazani yopiq Telegram kanalida saqlash.

Render bepul rejasida fayl tizimi vaqtinchalik: qayta ishga tushganda homework.db
yo'qoladi. Shu sababli baza faylining nusxasi (snapshot) yopiq kanalga hujjat sifatida
yuboriladi va pin qilinadi. Bot ishga tushganda pin qilingan hujjatni yuklab olib,
bazani tiklaydi. Keyingi saqlashlarda o'sha xabar ichidagi fayl almashtiriladi
(yangi xabar yaratilmaydi).

Botga kanalda admin huquqi kerak: xabar yuborish va xabarlarni tahrirlash.
"""
import asyncio
import logging
import os
import sqlite3
import tempfile
import time

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.types import FSInputFile, InputMediaDocument

import config as cfg
import db

CHECK_EVERY = 10  # soniya: o'zgarish bor-yo'qligini tekshirish
MIN_GAP = 30      # soniya: ikki saqlash orasidagi eng kam vaqt

_msg_id: int | None = None


def enabled() -> bool:
    return bool(cfg.channel_id)


def _valid(path: str) -> bool:
    try:
        con = sqlite3.connect(path)
        try:
            return con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except sqlite3.Error:
        return False


async def _download(bot: Bot, file_id: str) -> bool:
    folder = os.path.dirname(db.DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = db.DB_PATH + ".restore"
    await bot.download(file_id, destination=tmp)
    if _valid(tmp):
        os.replace(tmp, db.DB_PATH)
        return True
    os.remove(tmp)
    return False


async def restore(bot: Bot) -> None:
    """Bot ishga tushganda: pin qilingan snapshotdan bazani tiklaydi."""
    global _msg_id
    if not enabled():
        logging.warning("Baza kanali ulanmagan: baza faqat lokal faylda turadi. Admin: /setchannel")
        return
    try:
        chat = await bot.get_chat(cfg.channel_id)
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        logging.error("Baza kanaliga kirib bo'lmadi: %s", e)
        cfg.channel_id = 0
        await cfg.notify_admins(
            bot,
            "⚠️ Baza kanaliga kira olmadim (bot kanaldan chiqarilgan yoki admin emas). "
            "Botni kanalga admin qiling va qayta ulang: /setchannel",
        )
        return
    except TelegramAPIError as e:
        # Vaqtinchalik xato: bo'sh baza bilan davom etsak, kanaldagi nusxani bosib yuborishimiz mumkin.
        raise SystemExit(f"Baza kanaliga hozircha ulanib bo'lmadi ({e}). Qayta urinamiz.")
    pm = chat.pinned_message
    if not pm or not pm.document:
        logging.info("Kanalda snapshot yo'q: bo'sh baza bilan boshlanadi")
        return
    _msg_id = pm.message_id
    if os.path.exists(db.DB_PATH):
        logging.info("Lokal baza mavjud: tiklash o'tkazib yuborildi")
        return
    if await _download(bot, pm.document.file_id):
        logging.info("Baza kanaldagi snapshotdan tiklandi")
    else:
        raise SystemExit("Kanaldagi snapshot buzilgan, avtomatik tiklab bo'lmadi.")


async def attach(bot: Bot) -> str:
    """Admin yangi kanal ulaganda chaqiriladi. Natija: 'restored', 'kept' yoki 'new'.

    - kanalda snapshot bor va botdagi baza bo'sh: snapshotdan tiklanadi ('restored');
    - kanalda snapshot bor, lekin botda ma'lumot bor: eski snapshotga tegmaymiz, yangisi
      yuboriladi ('kept');
    - kanalda snapshot yo'q: yangisi yuboriladi ('new').
    """
    global _msg_id
    _msg_id = None
    chat = await bot.get_chat(cfg.channel_id)
    pm = chat.pinned_message
    if not (pm and pm.document):
        return "new"
    if db.is_empty():
        if await _download(bot, pm.document.file_id):
            db.init_db()
            _msg_id = pm.message_id
            return "restored"
        return "new"
    return "kept"


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
                    chat_id=cfg.channel_id,
                    message_id=_msg_id,
                )
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return
                logging.warning("Snapshotni tahrirlab bo'lmadi (%s): yangisi yuboriladi", e)
                _msg_id = None
        msg = await bot.send_document(
            cfg.channel_id,
            FSInputFile(path, filename="homework.db"),
            caption=caption,
            disable_notification=True,
        )
        await bot.pin_chat_message(cfg.channel_id, msg.message_id, disable_notification=True)
        _msg_id = msg.message_id
    finally:
        os.remove(path)


async def autosave_loop(bot: Bot) -> None:
    """Baza o'zgargan bo'lsa, har ~30 soniyada kanalga saqlaydi."""
    last = None
    while True:
        await asyncio.sleep(CHECK_EVERY)
        if not enabled() or not db.is_dirty():
            continue
        if last is not None and time.monotonic() - last < MIN_GAP:
            continue
        db.clear_dirty()
        try:
            await push(bot)
            last = time.monotonic()
        except Exception:
            logging.exception("Snapshotni kanalga saqlab bo'lmadi")
            db.mark_dirty()
