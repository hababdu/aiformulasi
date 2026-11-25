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
- `/students` – guruhdan yig'ilgan o'quvchilar ro'yxati
- `/setchannel`, `/setgroup` – baza kanali va o'quvchilar guruhini ulash
- `/config` – ulangan kanal va guruh
- `/backup` – zahira nusxani hozir kanalga va o'zingizga yuborish
- Kelgan ishda 5 / 4 / 3 / 2 yoki «Qayta topshirsin» tugmasini bosing, so'ng izoh yozing (yoki `/skip`)

**O'quvchi:**
- `/start` bosib ro'yxatdan o'tadi
- «📚 Vazifalar» → vazifani tanlab «📤 Topshirish»
- «📊 Natijalarim» – baholar va izohlar

## Eslatma
Ma'lumotlar `homework.db` (SQLite) faylida saqlanadi. O'quvchi botga `/start` bosmaguncha
yangi vazifa xabarini olmaydi.

## Render (bepul Web Service) da ishlatish

Render bepul rejasida fayl tizimi vaqtinchalik, shuning uchun hamma ma'lumot **yopiq Telegram kanalida**
saqlanadi. Muhit o'zgaruvchilaridan faqat `BOT_TOKEN` va `ADMIN_IDS` kerak. Kanal va guruh ID larini
o'qituvchi botning o'zida ulaydi:

1. Botga o'qituvchi sifatida `/start` bosing.
2. **Yopiq kanal:** kanal yarating va botni admin qiling (xabar yuborish va xabarlarni tahrirlash
   huquqlari bilan). Bot sizga tasdiqlash tugmasini yuboradi, «✅ Ha, ulash» ni bosing.
   Yoki `/setchannel -100...`.
3. **O'quvchilar guruhi:** botni guruhga qo'shing (admin qilish tavsiya etiladi), tugmani bosing
   yoki `/setgroup -100...`.
4. `/config` ulanganlarni ko'rsatadi. Sozlamalar sizning chatingizda pin qilingan «BOT_CONFIG»
   xabarida saqlanadi, uni o'chirmang.

Kanalda to'planadigan zahira:
- `homework.db` ning joriy nusxasi (pin qilingan, o'zgarishdan keyin ~30 soniyada yangilanadi).
  Qayta ishga tushganda baza shu fayldan tiklanadi. **Uni o'chirmang.**
- Har bir hodisa alohida xabar bo'lib to'planadi: yangi vazifa, o'quvchi topshirig'i (matn, rasm, fayl),
  baho va izoh, o'quvchining guruhga qo'shilishi/chiqishi.
- O'zgarish bo'lsa, soatiga bir marta CSV hisobot: `oquvchilar.csv`, `vazifalar.csv`,
  `topshiriqlar_ballar.csv`. `/backup` ularni darhol yuboradi.

Bepul Web Service 15 daqiqa trafik bo'lmasa uxlaydi, shuning uchun `keepalive.py` kichik HTTP server
ochadi va har 10 daqiqada (`PING_INTERVAL`, soniyalarda) o'z manziliga so'rov yuboradi.

Cheklov: bot to'satdan uzilsa, baza nusxasidagi oxirgi ~30 soniya o'zgarishlari yo'qolishi mumkin
(hodisa xabarlari esa kanalda qoladi). Telegram botga guruh a'zolari ro'yxatini bermaydi, shuning
uchun o'quvchilar guruhga kirganda, yozganda yoki botga `/start` bosganda ro'yxatga olinadi.
