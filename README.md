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

## Render (bepul Web Service) da ishlatish

Render bepul rejasida fayl tizimi vaqtinchalik, shuning uchun baza **yopiq Telegram kanalida** saqlanadi:

1. Yopiq kanal yarating, botni admin qiling (xabar yuborish, tahrirlash, pin qilish huquqlari bilan).
   Kanal ID sini `STORAGE_CHANNEL_ID` ga yozing. Bot kanalga `homework.db` nusxasini yuboradi va pin
   qiladi, har o'zgarishdan keyin (~30 soniyada) o'sha xabardagi faylni yangilaydi. Qayta ishga
   tushganda bazani shu fayldan tiklaydi. **Kanaldagi pin qilingan faylni o'chirmang.**
2. O'quvchilar guruhini botga ulang: botni guruhga qo'shing (admin qilish tavsiya etiladi) va ID sini
   `GROUP_ID` ga yozing. A'zolar kirish/chiqish hodisalaridan, guruhdagi xabarlardan va `/start`
   paytida yig'iladi. O'qituvchi `/students` bilan ro'yxatni ko'radi. Vazifa faqat guruh a'zolari
   bo'lgan va botni ishga tushirgan o'quvchilarga yuboriladi.
3. Bepul Web Service 15 daqiqa trafik bo'lmasa uxlaydi. `keepalive.py` kichik HTTP server ochadi va
   har 10 daqiqada (`PING_INTERVAL`, soniyalarda) o'zining ommaviy manziliga so'rov yuboradi.
4. `render.yaml` Blueprint orqali joylang, so'ng Dashboard da `BOT_TOKEN`, `ADMIN_IDS`,
   `STORAGE_CHANNEL_ID`, `GROUP_ID` qiymatlarini kiriting.

Cheklov: bot uzilib qolsa, oxirgi ~30 soniyadagi o'zgarishlar yo'qolishi mumkin.
