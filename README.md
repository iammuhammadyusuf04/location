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
- Kun oxirida (`SUMMARY_TIME`) PNG xarita, manzillar ro'yxati va interaktiv HTML xarita keladi.
- `/today`, `/yesterday` — istalgan vaqtda xaritani so'rash.

Eslatma: Telegram jonli lokatsiyani maksimal 8 soatga (yoki "doimiy") ulashadi; tugasa qayta ulashing. Bot 24/7 ishlaydigan serverda turishi kerak.
