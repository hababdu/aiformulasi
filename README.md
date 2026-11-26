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

**O'qituvchi** (`ADMIN_IDS` dagi akkauntlar) pastdagi tugmalar bilan ishlaydi:
- «➕ Yangi vazifa» – nom, tavsif, muddat kiritib vazifa berish (muddatsiz bo'lsa «⏭ Muddatsiz» tugmasi); hamma o'quvchilarga yuboriladi
- «📋 Vazifalar» – faol vazifalar, tekshirilmagan ishlar soni va har biri uchun «🔒 Yopish» tugmasi
- «📥 Tekshirilmagan» – tekshirilmagan ishlarni ko'rish; ishda 5 / 4 / 3 / 2 yoki «Qayta topshirsin» tugmasini bosing, so'ng izoh yozing (yoki «⏭ Izohsiz»)
- «👥 O'quvchilar» – guruhdan yig'ilgan o'quvchilar ro'yxati
- «📊 Statistika» – umumiy ko'rinish, vazifalar bo'yicha topshirish foizi, o'quvchilar reytingi va topshirmaganlar ro'yxati (bo'limlar tugmalar bilan almashadi)
- «🗂 Zahira nusxa» – zahira nusxani hozir kanalga va o'zingizga yuborish
- «⚙️ Sozlamalar» – ulangan kanal va guruhni ko'rish, «📣 Kanalni ulash» / «👥 Guruhni ulash»

Eski buyruqlar (`/newtask`, `/tasks`, `/pending`, `/close <id>`, `/students`, `/setchannel`, `/setgroup`,
`/config`, `/backup`) ham ishlaydi, lekin bot ularni ko'rsatmaydi. Har bir bosqichda «❌ Bekor qilish» tugmasi bor.

**O'quvchi:**
- `/start` bosib ro'yxatdan o'tadi
- «📚 Vazifalar» → vazifani tanlab «📤 Topshirish»
- «📊 Natijalarim» – topshirgan ishlar soni, o'rtacha baho, baholar va izohlar

## Eslatma
Ma'lumotlar `homework.db` (SQLite) faylida saqlanadi. O'quvchi botga `/start` bosmaguncha
yangi vazifa xabarini olmaydi.

## Render (bepul Web Service) da ishlatish

Render bepul rejasida fayl tizimi vaqtinchalik, shuning uchun hamma ma'lumot **yopiq Telegram kanalida**
saqlanadi. Muhit o'zgaruvchilaridan faqat `BOT_TOKEN` va `ADMIN_IDS` kerak. Kanal va guruh ID larini
o'qituvchi botning o'zida ulaydi:

1. Botga o'qituvchi sifatida `/start` bosing.
2. **Yopiq kanal** («⚙️ Sozlamalar» → «📣 Kanalni ulash»): kanal yarating va botni admin qiling (xabar yuborish va xabarlarni tahrirlash
   huquqlari bilan). Bot sizga tasdiqlash tugmasini yuboradi, «✅ Ha, ulash» ni bosing.
   Yoki kanal ID sini (`-100...`) tugmadan keyin botga yuboring.
3. **O'quvchilar guruhi** («👥 Guruhni ulash»): botni guruhga qo'shing (admin qilish tavsiya etiladi), tugmani bosing
   yoki guruh ID sini yuboring.
4. «⚙️ Sozlamalar» ulanganlarni ko'rsatadi. Sozlamalar sizning chatingizda pin qilingan «BOT_CONFIG»
   xabarida saqlanadi, uni o'chirmang.

Kanalda to'planadigan zahira:
- `homework.db` ning joriy nusxasi (pin qilingan, o'zgarishdan keyin ~30 soniyada yangilanadi).
  Qayta ishga tushganda baza shu fayldan tiklanadi. **Uni o'chirmang.**
- Har bir hodisa alohida xabar bo'lib to'planadi: yangi vazifa, o'quvchi topshirig'i (matn, rasm, fayl),
  baho va izoh, o'quvchining guruhga qo'shilishi/chiqishi.
- O'zgarish bo'lsa, soatiga bir marta CSV hisobot: `oquvchilar.csv`, `vazifalar.csv`,
  `topshiriqlar_ballar.csv`. «🗂 Zahira nusxa» ularni darhol yuboradi.

Bepul Web Service 15 daqiqa trafik bo'lmasa uxlaydi, shuning uchun `keepalive.py` kichik HTTP server
ochadi va har 10 daqiqada (`PING_INTERVAL`, soniyalarda) o'z manziliga so'rov yuboradi.

Cheklov: bot to'satdan uzilsa, baza nusxasidagi oxirgi ~30 soniya o'zgarishlari yo'qolishi mumkin
(hodisa xabarlari esa kanalda qoladi). Telegram botga guruh a'zolari ro'yxatini bermaydi, shuning
uchun o'quvchilar guruhga kirganda, yozganda yoki botga `/start` bosganda ro'yxatga olinadi.
