"""O'qituvchi uchun sozlash: baza kanali va o'quvchilar guruhini botning o'zida ulash."""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import archive
import config as cfg
import db
import persist
from ui import BTN_BACKUP, BTN_SETTINGS, NOT_CMD, NOT_MENU, cancel_kb

router = Router()


class Setup(StatesGroup):
    channel = State()
    group = State()

admin_only = F.func(lambda m: bool(m.from_user) and cfg.is_admin(m.from_user.id))


async def connect_channel(bot: Bot, chat_id: int) -> tuple[bool, str]:
    try:
        chat = await bot.get_chat(chat_id)
    except Exception as e:
        logging.warning("get_chat(%s) xato: %s", chat_id, e)
        return False, (
            f"Kanal topilmadi ({e}).\nBotni kanalga ADMIN qilib qo'shing (Kanal → Administratorlar → "
            "Administrator qo'shish → botni tanlang). Shunda men o'zim tasdiqlash tugmasini yuboraman, ID kerak emas."
        )
    if chat.type != "channel":
        return False, "Bu kanal emas. Baza uchun yopiq KANAL kerak."
    try:
        me = await bot.me()
        cm = await bot.get_chat_member(chat_id, me.id)
    except Exception:
        return False, "Botning kanaldagi huquqlarini bilib bo'lmadi."
    if cm.status != "administrator" or not (
        getattr(cm, "can_post_messages", False) and getattr(cm, "can_edit_messages", False)
    ):
        return False, (
            "Botni kanalda admin qiling: xabar yuborish va xabarlarni tahrirlash huquqlari bilan, "
            "so'ng qayta urinib ko'ring."
        )
    cfg.channel_id = chat_id
    try:
        mode = await persist.attach(bot)
    except Exception:
        logging.exception("Kanalni ulashda xato")
        cfg.channel_id = 0
        return False, "Kanalni ulab bo'lmadi, birozdan keyin qayta urinib ko'ring."
    await cfg.save(bot)
    db.mark_dirty()
    db.mark_report_dirty()
    archive.fire(archive.log_text(bot, "✅ Bot ulandi. Zahira nusxalari shu kanalda to'planadi."))
    note = {
        "restored": "Kanaldagi eski baza tiklandi.",
        "kept": "Botdagi ma'lumotlar saqlab qo'yildi, yangi baza nusxasi yuboriladi.",
        "new": "Baza nusxasi tez orada yuboriladi.",
    }[mode]
    return True, f"✅ «{chat.title}» baza va zahira kanali qilib ulandi. {note}"


async def connect_group(bot: Bot, chat_id: int) -> tuple[bool, str]:
    try:
        chat = await bot.get_chat(chat_id)
    except Exception as e:
        logging.warning("get_chat(%s) xato: %s", chat_id, e)
        return False, f"Guruh topilmadi ({e}). Botni guruhga qo'shing, men tasdiqlash tugmasini yuboraman."
    if chat.type not in ("group", "supergroup"):
        return False, "Bu guruh emas."
    cfg.group_id = chat_id
    await cfg.save(bot)
    return True, (
        f"✅ «{chat.title}» o'quvchilar guruhi qilib ulandi. A'zolar guruhga kirganda, yozganda "
        "yoki botga /start bosganda ro'yxatga qo'shiladi. Ro'yxat: /students"
    )


def _parse_id(command: CommandObject) -> int | None:
    try:
        return int((command.args or "").strip())
    except ValueError:
        return None


@router.message(Command("setchannel"), admin_only)
async def cmd_setchannel(message: Message, bot: Bot, command: CommandObject):
    chat_id = _parse_id(command)
    if chat_id is None:
        await message.answer(
            "Yopiq kanalni ulash: botni kanalga admin qiling (xabar yuborish va tahrirlash "
            "huquqlari bilan), men tasdiqlash tugmasini yuboraman.\n"
            "Yoki ID bilan: /setchannel -1001234567890"
        )
        return
    await message.answer((await connect_channel(bot, chat_id))[1])


@router.message(Command("setgroup"), admin_only)
async def cmd_setgroup(message: Message, bot: Bot, command: CommandObject):
    chat_id = _parse_id(command)
    if chat_id is None:
        await message.answer(
            "O'quvchilar guruhini ulash: botni guruhga qo'shing, men tasdiqlash tugmasini yuboraman.\n"
            "Yoki ID bilan: /setgroup -1001234567890"
        )
        return
    await message.answer((await connect_group(bot, chat_id))[1])


async def settings_text(bot: Bot) -> str:
    async def title(cid: int) -> str:
        if not cid:
            return "ulanmagan"
        try:
            return f"«{(await bot.get_chat(cid)).title}» ({cid})"
        except Exception:
            return f"{cid} (kirib bo'lmadi)"

    return (
        f"📣 Baza kanali: {await title(cfg.channel_id)}\n"
        f"👥 O'quvchilar guruhi: {await title(cfg.group_id)}"
    )


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📣 Kanalni ulash", callback_data="ask:channel")],
            [InlineKeyboardButton(text="👥 Guruhni ulash", callback_data="ask:group")],
        ]
    )


@router.message(Command("config"), admin_only)
@router.message(F.text == BTN_SETTINGS, admin_only)
async def cmd_config(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    await message.answer(await settings_text(bot), reply_markup=settings_kb())


@router.callback_query(F.data.startswith("ask:"))
async def cb_ask(cb: CallbackQuery, state: FSMContext):
    if not cfg.is_admin(cb.from_user.id):
        await cb.answer("Faqat o'qituvchi uchun", show_alert=True)
        return
    if cb.data.split(":", 1)[1] == "channel":
        await state.set_state(Setup.channel)
        text = (
            "Yopiq kanalni ulash:\n"
            "1. Kanal yarating (yoki mavjudini oching).\n"
            "2. Botni kanalga admin qiling (xabar yuborish va xabarlarni tahrirlash huquqlari "
            "bilan). Men sizga tasdiqlash tugmasini yuboraman.\n\n"
            "Yoki kanal ID sini (-100... bilan boshlanadi) shu yerga yuboring."
        )
    else:
        await state.set_state(Setup.group)
        text = (
            "O'quvchilar guruhini ulash:\n"
            "1. Botni guruhga qo'shing (admin qilish tavsiya etiladi). Men sizga tasdiqlash "
            "tugmasini yuboraman.\n\n"
            "Yoki guruh ID sini (-100... bilan boshlanadi) shu yerga yuboring."
        )
    await cb.answer()
    await cb.message.answer(text, reply_markup=cancel_kb())


async def _apply_id(message: Message, bot: Bot, state: FSMContext, connect) -> None:
    try:
        chat_id = int(message.text.strip())
    except ValueError:
        await message.answer(
            "ID raqam bo'lishi kerak, masalan -1001234567890. Qayta yuboring yoki bekor qiling.",
            reply_markup=cancel_kb(),
        )
        return
    ok, text = await connect(bot, chat_id)
    if ok:
        await state.clear()
    await message.answer(text, reply_markup=None if ok else cancel_kb())


@router.message(Setup.channel, F.text, NOT_MENU, NOT_CMD)
async def setup_channel_id(message: Message, bot: Bot, state: FSMContext):
    await _apply_id(message, bot, state, connect_channel)


@router.message(Setup.group, F.text, NOT_MENU, NOT_CMD)
async def setup_group_id(message: Message, bot: Bot, state: FSMContext):
    await _apply_id(message, bot, state, connect_group)


@router.message(Command("backup"), admin_only)
@router.message(F.text == BTN_BACKUP, admin_only)
async def cmd_backup(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    if cfg.channel_id:
        await persist.push(bot)
        await archive.send_report(bot, cfg.channel_id, "qo'lda so'raldi")
    await archive.send_report(bot, message.chat.id)
    await message.answer(
        "✅ Zahira nusxa kanalga va shu yerga yuborildi."
        if cfg.channel_id
        else "Zahira nusxa shu yerga yuborildi. Kanal ulanmagan: /setchannel"
    )


# Bot kanalga admin qilinganda yoki guruhga qo'shilganda, uni qo'shgan o'qituvchiga tasdiq tugmasi chiqadi.
@router.my_chat_member()
async def bot_membership(event: ChatMemberUpdated, bot: Bot):
    if not event.from_user or not cfg.is_admin(event.from_user.id):
        return  # begona odam qo'shgan bo'lsa, e'tibor bermaymiz
    chat, status = event.chat, event.new_chat_member.status
    if chat.type == "channel" and status == "administrator":
        data = f"setch:{chat.id}"
        text = f"📣 Bot «{chat.title}» kanaliga admin qilindi.\nBu kanalni baza va zahira kanali qilib ulaymi?"
    elif chat.type in ("group", "supergroup") and status in ("member", "administrator"):
        data = f"setgr:{chat.id}"
        text = f"👥 Bot «{chat.title}» guruhiga qo'shildi.\nBu guruhni o'quvchilar guruhi qilib ulaymi?"
    else:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Ha, ulash", callback_data=data)]])
    try:
        await bot.send_message(event.from_user.id, text, reply_markup=kb)
    except Exception:
        logging.warning("Admin %s ga tasdiq xabarini yuborib bo'lmadi (botga /start bosmagan)", event.from_user.id)


@router.callback_query(F.data.startswith("setch:") | F.data.startswith("setgr:"))
async def cb_connect(cb: CallbackQuery, bot: Bot, state: FSMContext):
    if not cfg.is_admin(cb.from_user.id):
        await cb.answer("Faqat o'qituvchi uchun", show_alert=True)
        return
    await state.clear()
    kind, raw = cb.data.split(":", 1)
    connect = connect_channel if kind == "setch" else connect_group
    await cb.answer()
    await cb.message.answer((await connect(bot, int(raw)))[1])
