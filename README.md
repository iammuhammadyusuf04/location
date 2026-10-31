# Location diary bot

Telegram bot: jonli lokatsiya bo'yicha har 10 daqiqada manzilingizni yozadi va kun oxirida xaritada yurgan yo'lingizni yuboradi.

## Ishga tushirish
1. @BotFather orqali bot yarating, tokenni oling.
2. `pip install -r requirements.txt`
3. `cp .env.example .env`, so'ng qiymatlarni to'ldiring (`ALLOWED_USER_ID` — faqat o'zingiz uchun).
4. `set -a; source .env; set +a; python bot.py`

## Foydalanish
- Botga `/start` yozing, so'ng 📎 → Lokatsiya → **Jonli lokatsiyani ulashish**.
- Bot har `INTERVAL_MIN` daqiqada `📍 14:30 — manzil` deb yozadi.
- Kun oxirida (`SUMMARY_TIME`) vaqtlar va turgan davomiyligi bilan manzillar ro'yxati hamda PWA xaritasiga havola keladi.
- `/today`, `/yesterday` — istalgan vaqtda xaritani so'rash.

Eslatma: Telegram jonli lokatsiyani maksimal 8 soatga (yoki "doimiy") ulashadi; tugasa qayta ulashing. Bot 24/7 ishlaydigan serverda turishi kerak.

## PWA (xarita ilovasi)
Lokatsiya baribir Telegram orqali yuboriladi; xaritani esa telefonda o'rnatiladigan ilova ko'rsatadi (sana tanlash, yo'l chizig'i, nuqtalar, manzillar ro'yxati, bugun uchun har daqiqada avtomatik yangilanish).

1. `.env` ga `WEB_KEY` (uzun maxfiy so'z) va `PUBLIC_URL` (HTTPS manzil) ni yozing.
2. Botni ishga tushiring: veb-server `PORT` (standart 8080) da ochiladi.
3. HTTPS kerak (PWA o'rnatilishi uchun). Eng oson yo'l: `cloudflared tunnel --url http://localhost:8080` yoki Caddy/nginx reverse proxy.
4. Botga `/app` yozing — kelgan havolani telefonda oching va «Bosh ekranga qo'shish» ni bosing.

Xaritada bir joyda (`STOP_RADIUS_M`, standart 100 m ichida) turgan nuqtalar bitta raqamlangan belgiga birlashadi va «08:10–09:40 (1 soat 30 daq)» ko'rinishida turgan vaqti yoziladi. Xaritani istalgancha yaqinlashtirish mumkin.
