"""Jonli lokatsiya kuzatuvchi Telegram bot.

- Jonli lokatsiya (Live Location) yuborsangiz, har INTERVAL_MIN daqiqada
  qayerda ekaningizni manzil bilan yozib turadi.
- Kun oxirida (SUMMARY_TIME) xaritada yurgan yo'lingizni rasm (PNG) va
  interaktiv xarita (HTML) ko'rinishida yuboradi.
"""
import asyncio
import hmac
import io
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID") or 0)
TZ = ZoneInfo(os.getenv("TZ", "Asia/Tashkent"))
SUMMARY_TIME = os.getenv("SUMMARY_TIME", "23:55")
INTERVAL_MIN = int(os.getenv("INTERVAL_MIN", "10"))
DB_PATH = os.getenv("DB_PATH", "locations.db")
WEB_KEY = os.getenv("WEB_KEY", "")  # PWA ga kirish kaliti; bo'sh bo'lsa veb o'chiq
WEB_PORT = int(os.getenv("PORT", "8080"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEB_DIR = Path(__file__).parent / "web"

log = logging.getLogger("locbot")


# ---------- Ma'lumotlar bazasi ----------
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS points ("
        "user_id INTEGER, chat_id INTEGER, ts INTEGER, lat REAL, lon REAL, addr TEXT)"
    )
    con.execute("CREATE INDEX IF NOT EXISTS ix_points ON points(user_id, ts)")
    return con


def last_ts(user_id: int) -> int:
    with db() as con:
        row = con.execute("SELECT MAX(ts) FROM points WHERE user_id=?", (user_id,)).fetchone()
    return row[0] or 0


def save_point(user_id, chat_id, ts, lat, lon, addr):
    with db() as con:
        con.execute("INSERT INTO points VALUES (?,?,?,?,?,?)", (user_id, chat_id, ts, lat, lon, addr))


def day_bounds(day):
    start = datetime(day.year, day.month, day.day, tzinfo=TZ)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def get_points(user_id: int, day):
    a, b = day_bounds(day)
    with db() as con:
        return con.execute(
            "SELECT ts, lat, lon, addr FROM points WHERE user_id=? AND ts>=? AND ts<? ORDER BY ts",
            (user_id, a, b),
        ).fetchall()


def active_users(day):
    a, b = day_bounds(day)
    with db() as con:
        return con.execute(
            "SELECT DISTINCT user_id, chat_id FROM points WHERE ts>=? AND ts<?", (a, b)
        ).fetchall()


# ---------- Manzil aniqlash (OpenStreetMap Nominatim) ----------
def reverse_geocode(lat: float, lon: float) -> str:
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "jsonv2", "accept-language": "uz,ru,en", "zoom": 18},
            headers={"User-Agent": "live-location-diary-bot/1.0"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("display_name") or f"{lat:.5f}, {lon:.5f}"
    except Exception as e:  # tarmoq xatosi botni to'xtatmasin
        log.warning("geocode xato: %s", e)
        return f"{lat:.5f}, {lon:.5f}"


# ---------- Xarita ----------
def render_png(points) -> bytes:
    from staticmap import CircleMarker, Line, StaticMap

    m = StaticMap(1200, 800, url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    coords = [(p[2], p[1]) for p in points]  # (lon, lat)
    if len(coords) > 1:
        m.add_line(Line(coords, "#1e66f5", 4))
    for i, c in enumerate(coords):
        color = "#16a34a" if i == 0 else "#dc2626" if i == len(coords) - 1 else "#1e66f5"
        m.add_marker(CircleMarker(c, "white", 16))
        m.add_marker(CircleMarker(c, color, 11))
    img = m.render(zoom=16) if len(coords) == 1 else m.render()
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def render_html(points) -> bytes:
    import folium

    latlons = [(p[1], p[2]) for p in points]
    fmap = folium.Map(location=latlons[0], zoom_start=15)
    if len(latlons) > 1:
        folium.PolyLine(latlons, color="#1e66f5", weight=4).add_to(fmap)
    for i, (ts, lat, lon, addr) in enumerate(points):
        t = datetime.fromtimestamp(ts, TZ).strftime("%H:%M")
        color = "green" if i == 0 else "red" if i == len(points) - 1 else "blue"
        folium.Marker((lat, lon), popup=f"{t}<br>{addr}", tooltip=t, icon=folium.Icon(color=color)).add_to(fmap)
    if len(latlons) > 1:
        fmap.fit_bounds(latlons)
    return fmap.get_root().render().encode()


def summary_text(points, day) -> str:
    lines, prev = [f"🗺 {day:%d.%m.%Y} — bugungi yo'lingiz ({len(points)} ta nuqta):"], None
    for ts, _, _, addr in points:
        if addr != prev:  # ketma-ket bir xil manzillarni birlashtiramiz
            lines.append(f"{datetime.fromtimestamp(ts, TZ):%H:%M} — {addr}")
            prev = addr
    return "\n".join(lines)


async def send_summary(bot, chat_id: int, user_id: int, day):
    points = get_points(user_id, day)
    if not points:
        await bot.send_message(chat_id, f"{day:%d.%m.%Y} kuni uchun saqlangan lokatsiya yo'q.")
        return
    png = await asyncio.to_thread(render_png, points)
    html = await asyncio.to_thread(render_html, points)
    text = summary_text(points, day)
    await bot.send_photo(chat_id, io.BytesIO(png), caption=text[:1000])
    for i in range(1000, len(text), 4000):
        await bot.send_message(chat_id, text[i : i + 4000])
    await bot.send_document(
        chat_id, io.BytesIO(html), filename=f"xarita_{day:%Y-%m-%d}.html",
        caption="Interaktiv xarita (brauzerda oching)",
    )


# ---------- PWA (veb-ilova) ----------
def web_user_id() -> int:
    if ALLOWED_USER_ID:
        return ALLOWED_USER_ID
    with db() as con:
        row = con.execute("SELECT user_id FROM points ORDER BY ts DESC LIMIT 1").fetchone()
    return row[0] if row else 0


async def api_points(request: web.Request) -> web.Response:
    if not hmac.compare_digest(request.headers.get("X-Key", ""), WEB_KEY):
        raise web.HTTPUnauthorized()
    try:
        day = datetime.strptime(request.query.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        day = datetime.now(TZ).date()
    rows = get_points(web_user_id(), day)
    return web.json_response([
        {"t": datetime.fromtimestamp(ts, TZ).strftime("%H:%M"), "ts": ts, "lat": lat, "lon": lon, "addr": addr}
        for ts, lat, lon, addr in rows
    ])


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")


async def start_web(app: Application):
    if not WEB_KEY:
        log.warning("WEB_KEY berilmagan — PWA o'chirilgan")
        return
    wa = web.Application()
    wa.router.add_get("/", index)
    wa.router.add_get("/api/points", api_points)
    wa.router.add_static("/", WEB_DIR)
    runner = web.AppRunner(wa)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    app.bot_data["web_runner"] = runner
    log.info("PWA: http://0.0.0.0:%s", WEB_PORT)


async def stop_web(app: Application):
    if runner := app.bot_data.get("web_runner"):
        await runner.cleanup()


# ---------- Handlerlar ----------
def allowed(update: Update) -> bool:
    return not ALLOWED_USER_ID or (update.effective_user and update.effective_user.id == ALLOWED_USER_ID)


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message  # jonli lokatsiya yangilanishlari edited_message bo'lib keladi
    if not msg or not msg.location or not allowed(update):
        return
    user_id, chat_id, now = update.effective_user.id, msg.chat_id, int(time.time())
    if now - last_ts(user_id) < INTERVAL_MIN * 60 - 5:
        return  # Telegram tez-tez yangilaydi, biz faqat har INTERVAL_MIN daqiqada yozamiz
    lat, lon = msg.location.latitude, msg.location.longitude
    addr = await asyncio.to_thread(reverse_geocode, lat, lon)
    save_point(user_id, chat_id, now, lat, lon, addr)
    await context.bot.send_message(chat_id, f"📍 {datetime.fromtimestamp(now, TZ):%H:%M} — {addr}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.reply_text(
        "Salom! Men qayerdaligingizni kuzataman.\n\n"
        "1) 📎 → Lokatsiya → «Jonli lokatsiyani ulashish» (8 soat/doimiy) ni tanlang.\n"
        f"2) Men har {INTERVAL_MIN} daqiqada manzilingizni yozib boraman.\n"
        f"3) Kun oxirida ({SUMMARY_TIME}) xaritada yo'lingizni yuboraman.\n\n"
        "/app — xarita ilovasi (PWA) havolasi\n/today — bugungi xarita\n/yesterday — kechagi xarita"
    )


async def cmd_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    if not (WEB_KEY and PUBLIC_URL):
        await update.message.reply_text("PWA sozlanmagan: .env da WEB_KEY va PUBLIC_URL ni to'ldiring.")
        return
    await update.message.reply_text(
        f"{PUBLIC_URL}/#key={WEB_KEY}\n\nBu havolani ochib, «Bosh ekranga qo'shish» (Install) ni bosing."
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await send_summary(context.bot, update.effective_chat.id, update.effective_user.id, datetime.now(TZ).date())


async def cmd_yesterday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        day = datetime.now(TZ).date() - timedelta(days=1)
        await send_summary(context.bot, update.effective_chat.id, update.effective_user.id, day)


async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    day = datetime.now(TZ).date()
    for user_id, chat_id in active_users(day):
        try:
            await send_summary(context.bot, chat_id, user_id, day)
        except Exception:
            log.exception("kunlik hisobot yuborilmadi: %s", user_id)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = Application.builder().token(BOT_TOKEN).post_init(start_web).post_shutdown(stop_web).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("app", cmd_app))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("yesterday", cmd_yesterday))
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    h, m = map(int, SUMMARY_TIME.split(":"))
    app.job_queue.run_daily(daily_job, time=dtime(h, m, tzinfo=TZ))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
