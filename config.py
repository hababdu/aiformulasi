"""Sozlamalar.

BOT_TOKEN va ADMIN_IDS muhit o'zgaruvchilaridan olinadi. Baza kanali va o'quvchilar guruhining
ID lari esa admin ularni botning o'zida ulaganda saqlanadi (/setchannel, /setgroup yoki
tasdiqlash tugmasi).

Render bepul rejasida fayl tizimi vaqtinchalik, shuning uchun ulangan ID lar admin bilan
yozishmada pin qilingan «BOT_CONFIG» xabarida saqlanadi va bot ishga tushganda o'sha yerdan
o'qiladi. Muhit o'zgaruvchilari (STORAGE_CHANNEL_ID, GROUP_ID) berilsa, ular ustun turadi.
"""
import json
import logging
import os

from dotenv import load_dotenv

load_dotenv()

ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

# Bot ishlayotganda o'zgarishi mumkin (admin ulaganda)
channel_id: int = int(os.getenv("STORAGE_CHANNEL_ID", "0") or 0)
group_id: int = int(os.getenv("GROUP_ID", "0") or 0)

TAG = "⚙️ BOT_CONFIG "
NOTE = "Bu xabarni o'chirmang va pin'dan olmang: bot sozlamalari (kanal va guruh) shu yerda saqlanadi."


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def load(bot) -> None:
    """Muhit o'zgaruvchisida berilmagan ID larni admin chatidagi pin qilingan xabardan o'qiydi."""
    global channel_id, group_id
    if channel_id and group_id:
        return
    for aid in ADMIN_IDS:
        try:
            pm = (await bot.get_chat(aid)).pinned_message
        except Exception:
            continue
        if not pm or not pm.text or not pm.text.startswith(TAG):
            continue
        try:
            data = json.loads(pm.text.split("\n")[0][len(TAG):])
        except ValueError:
            continue
        channel_id = channel_id or int(data.get("channel") or 0)
        group_id = group_id or int(data.get("group") or 0)
        logging.info("Sozlamalar admin chatidan o'qildi: kanal=%s guruh=%s", channel_id, group_id)
        return
    logging.info("Saqlangan sozlama topilmadi: kanal va guruh /setchannel, /setgroup bilan ulanadi")


async def save(bot) -> None:
    """Joriy kanal/guruh ID larini har bir adminning chatida pin qilib saqlaydi."""
    text = TAG + json.dumps({"channel": channel_id, "group": group_id}) + "\n" + NOTE
    for aid in ADMIN_IDS:
        try:
            old = (await bot.get_chat(aid)).pinned_message
            msg = await bot.send_message(aid, text, disable_notification=True)
            await bot.pin_chat_message(aid, msg.message_id, disable_notification=True)
            if old and old.text and old.text.startswith(TAG):
                await bot.delete_message(aid, old.message_id)
        except Exception:
            logging.warning("Sozlamani %s chatida saqlab bo'lmadi (admin botga /start bosganmi?)", aid)


async def notify_admins(bot, text: str) -> None:
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, text)
        except Exception:
            pass
