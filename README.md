# Location diary bot

Telegram bot: jonli lokatsiya bo'yicha har 10 daqiqada manzilingizni yozadi va kun oxirida xaritada yurgan yo'lingizni yuboradi.

## Ishga tushirish
1. @BotFather orqali bot yarating, tokenni oling.
2. `pip install -r requirements.txt`
3. `cp .env.example .env`, so'ng qiymatlarni to'ldiring (`ALLOWED_USER_ID` — faqat o'zingiz uchun).
4. `set -a; source .env; set +a; python bot.py`

## Foydalanish
- Botga `/start` yozing, so'ng 📎 → Lokatsiya → **Jonli lokatsiyani ulashish**.
- Bot har `INTERVAL_MIN` daqiqada `📍 14:30 — manzil` deb yozadi. Joyingiz o'zgarmasa ham (Telegram bunda yangilanish yubormaydi) oxirgi ma'lum joyni o'zi yozib boradi; signal 15 daqiqadan ortiq uzilsa, xabarda ogohlantiradi. `/stop` kuzatuvni to'xtatadi.
- Kun oxirida (`SUMMARY_TIME`) vaqtlar va turgan davomiyligi bilan manzillar ro'yxati hamda PWA xaritasiga havola keladi.
- `/today`, `/yesterday` — istalgan vaqtda xaritani so'rash.

Eslatma: Jonli lokatsiyani ulashishda **«Doimiy» (Until I turn it off)** ni tanlang — 8 soatlik cheklov bo'lmaydi. Signal `PAUSE_AFTER_H` (standart 6) soat kelmasa, bot bir marta xabar berib pauza qiladi va yangilanish kelganda o'zi davom etadi. Bot 24/7 ishlaydigan serverda turishi kerak.

## PWA (xarita ilovasi)
Lokatsiya baribir Telegram orqali yuboriladi; xaritani esa telefonda o'rnatiladigan ilova ko'rsatadi (sana tanlash, yo'l chizig'i, nuqtalar, manzillar ro'yxati, bugun uchun har daqiqada avtomatik yangilanish).

1. `.env` ga `WEB_KEY` (uzun maxfiy so'z) va `PUBLIC_URL` (HTTPS manzil) ni yozing.
2. Botni ishga tushiring: veb-server `PORT` (standart 8080) da ochiladi.
3. HTTPS kerak (PWA o'rnatilishi uchun). Eng oson yo'l: `cloudflared tunnel --url http://localhost:8080` yoki Caddy/nginx reverse proxy.
4. Botga `/app` yozing — kelgan havolani telefonda oching va «Bosh ekranga qo'shish» ni bosing.

Xaritada bir joyda (`STOP_RADIUS_M`, standart 100 m ichida) turgan nuqtalar bitta raqamlangan belgiga birlashadi va «08:10–09:40 (1 soat 30 daq)» ko'rinishida turgan vaqti yoziladi. Xaritani istalgancha yaqinlashtirish mumkin.

## Kunlar kesimida ko'rish va telefonda saqlash
- Ilovada 📅 tugmasi kunlar ro'yxatini ochadi: **Bugun, Kecha, 4 kun avval, 1 oy avval** ... (oylar bo'yicha guruhlangan, har kunda nuqtalar soni bilan). ‹ › tugmalari kunlar orasida yuradi, sana tanlagich ham bor.
- Ilova ochilganda barcha o'tgan kunlar fonda telefon xotirasiga (IndexedDB) yuklab qo'yiladi (ro'yxatda 📱 belgisi). Keyin ular internetsiz ham ochiladi. Faqat bugungi kun har safar serverdan yangilanadi.
- Ko'rilgan xarita bo'laklari ham keshlanadi, shuning uchun oldin ko'rgan joylaringiz oflayn ham ko'rinadi.

## Bir nechta jonli joylashuv: nom va rang
- Botga yuborilgan **har bir jonli lokatsiya alohida joylashuv** bo'ladi (masalan telefonim, onam, mashina). Bot yangi joylashuvga avtomatik nom («Joylashuv 1») va rang beradi, so'ng nom so'raydi: shu xabarga **javob qilib** nom yozing.
- **Nom ham, rang ham takrorlanmaydi**: band nom yoki rang tanlansa, bot rad etadi.
- `/list` — joylashuvlar; `/rename Eski = Yangi`; `/color Nom = Qizil` (yoki `#RRGGBB`); `/stop [Nom]` — to'xtatish.
- PWA da har joylashuv o'z rangi va nomi bilan chiziladi; yuqoridagi rangli tugmalar (chip) orqali birini yashirish/ko'rsatish mumkin. Nom/rang o'zgartirilsa, eski kunlarda ham yangisi ko'rinadi.
- Bir nechta odam (masalan oila) ishlatishi uchun `ALLOWED_USER_ID` ga ularning ID larini vergul bilan yozing. Eslatma: PWA hamma joylashuvlarni ko'rsatadi, `WEB_KEY` ni faqat ishonchli odamlarga bering.

## Egasi va «signal uzildi» ogohlantirishi
- `OWNER_ID` (yoki `ALLOWED_USER_ID` dagi birinchi ID) — **egasi**. Barcha 10 daqiqalik xabarlar, ogohlantirishlar va kunlik hisobotlar egasiga keladi (egasi botga bir marta `/start` bosgan bo'lishi kerak). Farzand o'z telefonidan faqat jonli lokatsiyani ulaydi; unga «Joylashuvingiz ulandi» deb yoziladi, xolos. Egasi `/list`, `/rename`, `/color`, `/stop` bilan hamma joylashuvni boshqaradi.
- Biror joylashuvdan `ALERT_AFTER_MIN` (standart 60) daqiqa signal kelmasa, egasiga bir marta «⚠️ Ali dan signal uzildi — oxirgi joy: ...» yoziladi. Signal qaytsa «✅ Ali signali qayta tiklandi» keladi. Jonli lokatsiya muddati tugagan bo'lsa ham shunday ogohlantiradi.

## PWA ni bot o'zi beradi (GitHub Pages shart emas)
Veb-ilova bot bilan bir serverda ishlaydi (`PORT`, standart 8080). GitHub Actions/Pages kerak emas.

1. Serverga HTTPS bering, masalan: `cloudflared tunnel --url http://localhost:8080`.
2. `.env` ga `WEB_KEY` va `PUBLIC_URL` (HTTPS manzil) ni yozing. `PWA_URL` ni bo'sh qoldiring.
3. Botga `/app` yozing, kelgan havolani telefonda oching va «Bosh ekranga qo'shish» ni bosing.
4. Yangilash: serverda `git pull`, so'ng botni qayta ishga tushiring.

(`PWA_URL` — ixtiyoriy: PWA ni alohida statik hostingdan berish uchun; bo'sh bo'lsa ishlatilmaydi.)

## Kunlar kesimida ko'rish va telefonda saqlash
- Ilovada 📅 tugmasi kunlar ro'yxatini ochadi: **Bugun, Kecha, 4 kun avval, 1 oy avval** ... (oylar bo'yicha guruhlangan, har kunda nuqtalar soni bilan). ‹ › tugmalari kunlar orasida yuradi, sana tanlagich ham bor.
- Ilova ochilganda barcha o'tgan kunlar fonda telefon xotirasiga (IndexedDB) yuklab qo'yiladi (ro'yxatda 📱 belgisi). Keyin ular internetsiz ham ochiladi. Faqat bugungi kun har safar serverdan yangilanadi.
- Ko'rilgan xarita bo'laklari ham keshlanadi, shuning uchun oldin ko'rgan joylaringiz oflayn ham ko'rinadi.

## Bir nechta jonli joylashuv: nom va rang
- Botga yuborilgan **har bir jonli lokatsiya alohida joylashuv** bo'ladi (masalan telefonim, onam, mashina). Bot yangi joylashuvga avtomatik nom («Joylashuv 1») va rang beradi, so'ng nom so'raydi: shu xabarga **javob qilib** nom yozing.
- **Nom ham, rang ham takrorlanmaydi**: band nom yoki rang tanlansa, bot rad etadi.
- `/list` — joylashuvlar; `/rename Eski = Yangi`; `/color Nom = Qizil` (yoki `#RRGGBB`); `/stop [Nom]` — to'xtatish.
- PWA da har joylashuv o'z rangi va nomi bilan chiziladi; yuqoridagi rangli tugmalar (chip) orqali birini yashirish/ko'rsatish mumkin. Nom/rang o'zgartirilsa, eski kunlarda ham yangisi ko'rinadi.
- Bir nechta odam (masalan oila) ishlatishi uchun `ALLOWED_USER_ID` ga ularning ID larini vergul bilan yozing. Eslatma: PWA hamma joylashuvlarni ko'rsatadi, `WEB_KEY` ni faqat ishonchli odamlarga bering.

## Egasi va «signal uzildi» ogohlantirishi
- `OWNER_ID` (yoki `ALLOWED_USER_ID` dagi birinchi ID) — **egasi**. Barcha 10 daqiqalik xabarlar, ogohlantirishlar va kunlik hisobotlar egasiga keladi (egasi botga bir marta `/start` bosgan bo'lishi kerak). Farzand o'z telefonidan faqat jonli lokatsiyani ulaydi; unga «Joylashuvingiz ulandi» deb yoziladi, xolos. Egasi `/list`, `/rename`, `/color`, `/stop` bilan hamma joylashuvni boshqaradi.
- Biror joylashuvdan `ALERT_AFTER_MIN` (standart 60) daqiqa signal kelmasa, egasiga bir marta «⚠️ Ali dan signal uzildi — oxirgi joy: ...» yoziladi. Signal qaytsa «✅ Ali signali qayta tiklandi» keladi. Jonli lokatsiya muddati tugagan bo'lsa ham shunday ogohlantiradi.

## PWA ni GitHub Pages'dan berish
PWA fayllari (`web/`) GitHub Pages'da turadi va `main` ga har push qilinganda avtomatik yangilanadi (`.github/workflows/pages.yml`). Ma'lumotlar bot serveridan olinadi.

1. Repo → **Settings → Pages → Source: GitHub Actions** ni tanlang (bir marta).
2. Bot serveri HTTPS manzilda turishi kerak (`PUBLIC_URL`, masalan Cloudflare Tunnel). `.env` ga `PUBLIC_URL` va `PWA_URL=https://<login>.github.io/location` ni yozing.
3. Botga `/app` yozing: havola Pages manziliga boradi va ichida kalit hamda server manzili bor (`#key=...&api=...`). Telefonda oching va «Bosh ekranga qo'shish» ni bosing. Havola `#` dan keyingi qismi serverga yuborilmaydi va ochilgach manzil satridan o'chadi.
