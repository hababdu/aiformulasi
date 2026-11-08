# Vazifa tekshiruvchi Telegram bot

O'qituvchi vazifa beradi, o'quvchilar bot orqali topshiradi (matn, rasm yoki fayl),
o'qituvchi esa tugmalar bilan baho qo'yadi yoki qayta topshirishni so'raydi.

## Ishga tushirish

1. @BotFather orqali bot yarating va tokenni oling.
2. `.env.example` ni `.env` ga nusxalab, `BOT_TOKEN` va `ADMIN_IDS` ni to'ldiring.
3. O'rnatish va ishga tushirish:

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

## Foydalanish

**O'qituvchi** (`ADMIN_IDS` dagi akkauntlar):
- `/newtask` – nom, tavsif, muddat kiritib vazifa berish (hamma o'quvchilarga yuboriladi)
- `/tasks` – faol vazifalar va tekshirilmagan ishlar soni
- `/pending` – tekshirilmagan ishlarni ko'rish
- `/close <id>` – vazifani yopish
- Kelgan ishda 5 / 4 / 3 / 2 yoki «Qayta topshirsin» tugmasini bosing, so'ng izoh yozing (yoki `/skip`)

**O'quvchi:**
- `/start` bosib ro'yxatdan o'tadi
- «📚 Vazifalar» → vazifani tanlab «📤 Topshirish»
- «📊 Natijalarim» – baholar va izohlar

## Eslatma
Ma'lumotlar `homework.db` (SQLite) faylida saqlanadi. O'quvchi botga `/start` bosmaguncha
yangi vazifa xabarini olmaydi.
