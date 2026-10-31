"""Jonli lokatsiya kuzatuvchi Telegram bot.

- Botga bir nechta jonli lokatsiya (Live Location) qo'shish mumkin; har biri o'z
  nomi va rangiga ega ("izlovchi"). Nom ham, rang ham takrorlanmaydi.
- Har INTERVAL_MIN daqiqada har bir izlovchi uchun manzil botga yoziladi.
- Kun oxirida (SUMMARY_TIME) hisobot, xaritada esa PWA ilovasi ko'rsatadi.
"""
import asyncio
import colorsys
import hmac
import io
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from datetime import time as dtime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from aiohttp import web
from telegram import ForceReply, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
# Ruxsat etilgan Telegram ID lar (vergul bilan). Bo'sh bo'lsa - hamma uchun ochiq.
ALLOWED_LIST = [int(x) for x in re.split(r"[,\s]+", os.getenv("ALLOWED_USER_ID", "")) if x]
ALLOWED_IDS = set(ALLOWED_LIST)
# Egasi (ota-ona): xabarlar, ogohlantirishlar va hisobotlar shu odamga keladi. Bo'sh bo'lsa - birinchi ruxsat etilgan ID.
OWNER_IDS = [int(x) for x in re.split(r"[,\s]+", os.getenv("OWNER_ID", "")) if x] or ALLOWED_LIST[:1]
ALERT_AFTER_MIN = int(os.getenv("ALERT_AFTER_MIN", "60"))  # shuncha daqiqa signal bo'lmasa egasiga xabar
TZ = ZoneInfo(os.getenv("TZ", "Asia/Tashkent"))
SUMMARY_TIME = os.getenv("SUMMARY_TIME", "23:55")
INTERVAL_MIN = int(os.getenv("INTERVAL_MIN", "10"))
PAUSE_AFTER_H = int(os.getenv("PAUSE_AFTER_H", "6"))  # shuncha soat signal bo'lmasa - pauza
DB_PATH = os.getenv("DB_PATH", "locations.db")
WEB_KEY = os.getenv("WEB_KEY", "")  # PWA ga kirish kaliti; bo'sh bo'lsa veb o'chiq
WEB_PORT = int(os.getenv("PORT", "8080"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEB_DIR = Path(__file__).parent / "web"
# GitHub Pages manzili (masalan https://user.github.io/location). Berilsa PWA shu yerdan ochiladi,
# ma'lumot esa PUBLIC_URL dagi bot serveridan olinadi (CORS shu manzilga ruxsat beradi).
PWA_URL = os.getenv("PWA_URL", "").rstrip("/")

log = logging.getLogger("locbot")

# (nomi, hex, emoji) - yangi izlovchiga ketma-ket band bo'lmagan rang beriladi
PALETTE = [
    ("Qizil", "#e11d48", "🔴"), ("Ko'k", "#2563eb", "🔵"), ("Yashil", "#16a34a", "🟢"),
    ("To'q sariq", "#f97316", "🟠"), ("Binafsha", "#9333ea", "🟣"), ("Sariq", "#eab308", "🟡"),
    ("Jigarrang", "#92400e", "🟤"), ("Pushti", "#ec4899", "🩷"), ("Moviy", "#0891b2", "🩵"),
    ("Qora", "#111827", "⚫"),
]


# ---------- Ma'lumotlar bazasi ----------
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE IF NOT EXISTS points ("
        "user_id INTEGER, chat_id INTEGER, ts INTEGER, lat REAL, lon REAL, addr TEXT, tracker_id INTEGER)"
    )
    cols = {r[1] for r in con.execute("PRAGMA table_info(points)")}
    if "tracker_id" not in cols:  # eski bazadan o'tish
        con.execute("ALTER TABLE points ADD COLUMN tracker_id INTEGER")
    con.execute(
        "CREATE TABLE IF NOT EXISTS trackers ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER, message_id INTEGER, "
        "name TEXT, color TEXT, prompt_id INTEGER, stopped INTEGER DEFAULT 0)"
    )
    tcols = {r[1] for r in con.execute("PRAGMA table_info(trackers)")}
    for col in ("alerted", "prompt_chat"):
        if col not in tcols:
            con.execute(f"ALTER TABLE trackers ADD COLUMN {col} INTEGER DEFAULT 0")
    con.execute(
        "CREATE TABLE IF NOT EXISTS tracker_live ("
        "tracker_id INTEGER PRIMARY KEY, lat REAL, lon REAL, seen INTEGER, expires INTEGER)"
    )
    con.execute("DROP TABLE IF EXISTS live")
    con.execute("CREATE INDEX IF NOT EXISTS ix_points ON points(tracker_id, ts)")
    return con


def migrate_orphans():
    """Izlovchisiz eski nuqtalarni har bir foydalanuvchi uchun «Asosiy» izlovchiga biriktiradi."""
    with db() as con:
        for r in con.execute("SELECT DISTINCT user_id, chat_id FROM points WHERE tracker_id IS NULL").fetchall():
            t = new_tracker(r["user_id"], r["chat_id"], 0, name="Asosiy", con=con)
            con.execute("UPDATE points SET tracker_id=? WHERE tracker_id IS NULL AND user_id=?", (t["id"], r["user_id"]))


def norm(s: str) -> str:
    return " ".join(s.lower().replace("’", "'").replace("‘", "'").split())


def free_color(con) -> str:
    used = {r[0].lower() for r in con.execute("SELECT color FROM trackers")}
    for _, hx, _ in PALETTE:
        if hx not in used:
            return hx
    h = 0.0
    while True:  # palitra tugasa - noyob rang hosil qilamiz
        h = (h + 0.618034) % 1
        hx = "#%02x%02x%02x" % tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, 0.7, 0.85))
        if hx not in used:
            return hx


def new_tracker(user_id, chat_id, message_id, name=None, con=None) -> dict:
    own = con is None
    con = con or db()
    names = {norm(r[0]) for r in con.execute("SELECT name FROM trackers")}
    if not name or norm(name) in names:
        base, n = name or "Joylashuv", 1
        while norm(f"{base} {n}") in names:
            n += 1
        name = f"{base} {n}"
    cur = con.execute(
        "INSERT INTO trackers (user_id, chat_id, message_id, name, color) VALUES (?,?,?,?,?)",
        (user_id, chat_id, message_id, name, free_color(con)),
    )
    t = dict(con.execute("SELECT * FROM trackers WHERE id=?", (cur.lastrowid,)).fetchone())
    if own:
        con.commit()
        con.close()
    return t


def tracker_by_msg(chat_id, message_id):
    with db() as con:
        r = con.execute("SELECT * FROM trackers WHERE chat_id=? AND message_id=?", (chat_id, message_id)).fetchone()
    return dict(r) if r else None


def tracker_by_prompt(chat_id, prompt_id):
    with db() as con:
        r = con.execute("SELECT * FROM trackers WHERE prompt_chat=? AND prompt_id=?", (chat_id, prompt_id)).fetchone()
    return dict(r) if r else None


def user_trackers(user_id) -> list[dict]:
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM trackers WHERE user_id=? ORDER BY id", (user_id,))]


def visible_trackers(user_id) -> list[dict]:
    """Egasi hamma joylashuvni ko'radi, boshqalar faqat o'zinikini."""
    return all_trackers() if user_id in OWNER_IDS else user_trackers(user_id)


def all_trackers() -> list[dict]:
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM trackers ORDER BY id")]


def find_tracker(user_id, name):
    return next((t for t in visible_trackers(user_id) if norm(t["name"]) == norm(name)), None)


def set_prompt(tid, chat_id, message_id):
    with db() as con:
        con.execute("UPDATE trackers SET prompt_id=?, prompt_chat=? WHERE id=?", (message_id, chat_id, tid))


def set_alerted(tid, flag: bool):
    with db() as con:
        con.execute("UPDATE trackers SET alerted=? WHERE id=?", (int(flag), tid))


def silent_live(now):
    """Jonli (yoki pauzadagi) izlovchilar, signali ALERT_AFTER_MIN dan beri yo'q va hali xabar berilmagan."""
    with db() as con:
        return con.execute(
            "SELECT t.*, l.seen AS seen FROM tracker_live l JOIN trackers t ON t.id=l.tracker_id "
            "WHERE t.stopped=0 AND t.alerted=0 AND l.expires!=0 AND l.seen<?", (now - ALERT_AFTER_MIN * 60,)
        ).fetchall()


def rename_tracker(tid, name) -> str | None:
    name = " ".join(name.split())[:40]
    if not name:
        return "Nom bo'sh bo'lmasin."
    with db() as con:
        if any(norm(r[0]) == norm(name) for r in con.execute("SELECT name FROM trackers WHERE id!=?", (tid,))):
            return f"«{name}» nomi band, boshqa nom tanlang."
        con.execute("UPDATE trackers SET name=? WHERE id=?", (name, tid))
    return None


def set_color(tid, spec) -> str | None:
    spec = spec.strip()
    hit = next((p for p in PALETTE if norm(p[0]) == norm(spec)), None)
    if hit:
        hx = hit[1]
    elif re.fullmatch(r"#[0-9a-fA-F]{6}", spec):
        hx = spec.lower()
    else:
        return "Rang topilmadi. Mavjud: " + ", ".join(p[0] for p in PALETTE) + " yoki #RRGGBB."
    with db() as con:
        if any(r[0].lower() == hx for r in con.execute("SELECT color FROM trackers WHERE id!=?", (tid,))):
            return "Bu rang boshqa joylashuvda ishlatilgan, boshqa rang tanlang."
        con.execute("UPDATE trackers SET color=? WHERE id=?", (hx, tid))
    return None


def set_stopped(tid, stopped: bool):
    with db() as con:
        con.execute("UPDATE trackers SET stopped=? WHERE id=?", (int(stopped), tid))
        if stopped:
            con.execute("DELETE FROM tracker_live WHERE tracker_id=?", (tid,))


def emoji_of(t) -> str:
    return next((p[2] for p in PALETTE if p[1] == t["color"].lower()), "●")


def last_ts(tid: int) -> int:
    with db() as con:
        return con.execute("SELECT MAX(ts) FROM points WHERE tracker_id=?", (tid,)).fetchone()[0] or 0


def last_point(tid: int):
    with db() as con:
        return con.execute(
            "SELECT ts, lat, lon, addr FROM points WHERE tracker_id=? ORDER BY ts DESC LIMIT 1", (tid,)
        ).fetchone()


def set_live(tid, lat, lon, seen, expires):
    with db() as con:
        con.execute("INSERT OR REPLACE INTO tracker_live VALUES (?,?,?,?,?)", (tid, lat, lon, seen, expires))


def active_live(now):
    with db() as con:
        return con.execute(
            "SELECT t.*, l.lat AS lat, l.lon AS lon, l.seen AS seen FROM tracker_live l "
            "JOIN trackers t ON t.id=l.tracker_id WHERE l.expires>? AND t.stopped=0", (now,)
        ).fetchall()


def save_point(t, ts, lat, lon, addr):
    with db() as con:
        con.execute(
            "INSERT INTO points VALUES (?,?,?,?,?,?,?)", (t["user_id"], t["chat_id"], ts, lat, lon, addr, t["id"])
        )


def day_bounds(day):
    start = datetime(day.year, day.month, day.day, tzinfo=TZ)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def get_points(tid: int, day):
    a, b = day_bounds(day)
    with db() as con:
        return [tuple(r) for r in con.execute(
            "SELECT ts, lat, lon, addr FROM points WHERE tracker_id=? AND ts>=? AND ts<? ORDER BY ts", (tid, a, b)
        )]


def active_users(day):
    a, b = day_bounds(day)
    with db() as con:
        return [tuple(r) for r in con.execute(
            "SELECT DISTINCT user_id, chat_id FROM points WHERE ts>=? AND ts<?", (a, b)
        )]


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


# ---------- To'xtashlar va hisobot ----------
STOP_RADIUS_M = int(os.getenv("STOP_RADIUS_M", "100"))


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = radians(lat1), radians(lat2)
    a = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))


def fmt_dur(mins: int) -> str:
    h, m = divmod(mins, 60)
    return f"{h} soat {m} daq" if h and m else f"{h} soat" if h else f"{m} daq"


def build_stops(points) -> list[dict]:
    """Ketma-ket yaqin (STOP_RADIUS_M ichidagi) nuqtalarni bitta joyga birlashtiradi."""
    stops: list[dict] = []
    for ts, lat, lon, addr in points:
        cur = stops[-1] if stops else None
        if cur and haversine_m(cur["lat"], cur["lon"], lat, lon) <= STOP_RADIUS_M:
            cur["to"], cur["n"] = ts, cur["n"] + 1
        else:
            stops.append({"lat": lat, "lon": lon, "addr": addr, "from": ts, "to": ts, "n": 1})
    for st in stops:
        st["mins"] = (st["to"] - st["from"]) // 60
    return stops


def day_groups(user_id, day):
    """[(izlovchi, nuqtalar)] - shu kuni nuqtasi bor izlovchilar."""
    groups = [(t, get_points(t["id"], day)) for t in visible_trackers(user_id)]
    return [(t, p) for t, p in groups if p]


def render_html(groups) -> bytes:
    import folium

    allll = [(p[1], p[2]) for _, pts in groups for p in pts]
    fmap = folium.Map(location=allll[0], zoom_start=15)
    for t, pts in groups:
        latlons = [(p[1], p[2]) for p in pts]
        if len(latlons) > 1:
            folium.PolyLine(latlons, color=t["color"], weight=4).add_to(fmap)
        for ts, lat, lon, addr in pts:
            hm = datetime.fromtimestamp(ts, TZ).strftime("%H:%M")
            folium.CircleMarker((lat, lon), radius=6, color=t["color"], fill=True, fill_opacity=1,
                                popup=f"{t['name']} {hm}<br>{addr}", tooltip=f"{t['name']} {hm}").add_to(fmap)
    if len(allll) > 1:
        fmap.fit_bounds(allll)
    return fmap.get_root().render().encode()


def summary_text(groups, day) -> str:
    lines = [f"🗺 {day:%d.%m.%Y} — kunlik hisobot"]
    for t, points in groups:
        stops = build_stops(points)
        lines.append(f"\n{emoji_of(t)} {t['name']} ({len(stops)} ta joy):")
        for st in stops:
            t0, t1 = (datetime.fromtimestamp(st[k], TZ).strftime("%H:%M") for k in ("from", "to"))
            when = f"{t0}–{t1} ({fmt_dur(st['mins'])})" if st["mins"] else t0
            lines.append(f"{when} — {st['addr']}")
    return "\n".join(lines)


async def send_summary(bot, chat_id: int, user_id: int, day):
    groups = day_groups(user_id, day)
    if not groups:
        await bot.send_message(chat_id, f"{day:%d.%m.%Y} kuni uchun saqlangan lokatsiya yo'q.")
        return
    text = summary_text(groups, day)
    for i in range(0, len(text), 4000):
        await bot.send_message(chat_id, text[i : i + 4000])
    if WEB_KEY and PUBLIC_URL:
        await bot.send_message(chat_id, f"🔎 Xaritada ko'rish (yaqinlashtirish mumkin): {app_link(day)}")
    else:
        html = await asyncio.to_thread(render_html, groups)
        await bot.send_document(chat_id, io.BytesIO(html), filename=f"xarita_{day:%Y-%m-%d}.html")


# ---------- PWA (veb-ilova) ----------
def app_link(day=None) -> str:
    """PWA ochiladigan havola (kalit va kerak bo'lsa API manzili bilan)."""
    parts = [f"key={WEB_KEY}"]
    if PWA_URL:
        parts.append(f"api={PUBLIC_URL}")
    if day:
        parts.append(f"date={day:%Y-%m-%d}")
    return f"{PWA_URL or PUBLIC_URL}/#" + "&".join(parts)


@web.middleware
async def cors(request: web.Request, handler):
    origin = request.headers.get("Origin", "")
    allowed_origin = bool(PWA_URL) and origin == "/".join(PWA_URL.split("/")[:3])  # faqat Pages domeni
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            resp = e
    if allowed_origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Headers"] = "X-Key"
        resp.headers["Vary"] = "Origin"
    return resp


def check_key(request: web.Request):
    if not hmac.compare_digest(request.headers.get("X-Key", ""), WEB_KEY):
        raise web.HTTPUnauthorized()


async def api_trackers(request: web.Request) -> web.Response:
    check_key(request)
    return web.json_response([{"id": t["id"], "name": t["name"], "color": t["color"], "stopped": bool(t["stopped"])}
                              for t in all_trackers()])


async def api_days(request: web.Request) -> web.Response:
    """Ma'lumoti bor barcha kunlar va ulardagi nuqtalar soni."""
    check_key(request)
    with db() as con:
        rows = con.execute("SELECT ts FROM points").fetchall()
    counts: dict[str, int] = {}
    for (ts,) in rows:
        d = datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d")
        counts[d] = counts.get(d, 0) + 1
    return web.json_response([{"date": d, "n": n} for d, n in sorted(counts.items(), reverse=True)])


async def api_points(request: web.Request) -> web.Response:
    check_key(request)
    try:
        day = datetime.strptime(request.query.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        day = datetime.now(TZ).date()
    hm = lambda ts: datetime.fromtimestamp(ts, TZ).strftime("%H:%M")
    out = []
    for t in all_trackers():
        rows = get_points(t["id"], day)
        if rows:
            out.append({
                "id": t["id"],
                "points": [{"t": hm(ts), "lat": lat, "lon": lon, "addr": addr} for ts, lat, lon, addr in rows],
                "stops": [{**st, "t0": hm(st["from"]), "t1": hm(st["to"]), "dur": fmt_dur(st["mins"]) if st["mins"] else ""}
                          for st in build_stops(rows)],
            })
    return web.json_response({"trackers": out})


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")


async def start_web(app: Application):
    if not WEB_KEY:
        log.warning("WEB_KEY berilmagan — PWA o'chirilgan")
        return
    wa = web.Application(middlewares=[cors])
    wa.router.add_get("/", index)
    wa.router.add_get("/api/points", api_points)
    wa.router.add_get("/api/days", api_days)
    wa.router.add_get("/api/trackers", api_trackers)
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
    return not ALLOWED_IDS or (update.effective_user and update.effective_user.id in ALLOWED_IDS)


async def notify(bot, t, text, **kw):
    """Egasiga (bo'lmasa joylashuv chatiga) xabar yuboradi; birinchi yuborilgan xabarni qaytaradi."""
    first = None
    for chat in OWNER_IDS or [t["chat_id"]]:
        try:
            m = await bot.send_message(chat, text, **kw)
            first = first or m
        except Exception as e:  # masalan, egasi botga /start bosmagan
            log.warning("xabar yuborilmadi (%s): %s", chat, e)
    return first


async def record(bot, t, lat, lon, now, stale_min=0):
    """Nuqtani saqlaydi va botga xabar yozadi."""
    prev = last_point(t["id"])
    if prev and (prev["lat"], prev["lon"]) == (lat, lon):
        addr = prev["addr"]  # joy o'zgarmagan - qayta so'ramaymiz
    else:
        addr = await asyncio.to_thread(reverse_geocode, lat, lon)
    save_point(t, now, lat, lon, addr)
    note = f"\n⚠️ signal {stale_min} daq oldin uzilgan, oxirgi ma'lum joy" if stale_min else ""
    await notify(bot, t, f"📍 {emoji_of(t)} {t['name']} · {datetime.fromtimestamp(now, TZ):%H:%M} — {addr}{note}")


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message  # jonli lokatsiya yangilanishlari edited_message bo'lib keladi
    if not msg or not msg.location or not allowed(update):
        return
    user_id, chat_id, now = update.effective_user.id, msg.chat_id, int(time.time())
    lat, lon = msg.location.latitude, msg.location.longitude
    live = msg.location.live_period  # None bo'lsa - oddiy (bir martalik) lokatsiya
    t, is_new = tracker_by_msg(chat_id, msg.message_id), False
    if not t and not live:  # bir martalik lokatsiya - foydalanuvchining oxirgi izlovchisiga
        mine = user_trackers(user_id)
        t = mine[-1] if mine else None
    if not t:
        t, is_new = new_tracker(user_id, chat_id, msg.message_id), True
    if t["stopped"]:
        return
    set_live(t["id"], lat, lon, now, int(msg.date.timestamp()) + live if live else 0)
    if t.get("alerted"):  # signal qaytdi
        set_alerted(t["id"], False)
        await notify(context.bot, t, f"✅ {emoji_of(t)} {t['name']} signali qayta tiklandi.")
    if is_new:
        p = await notify(
            context.bot, t,
            f"✅ Yangi jonli joylashuv qo'shildi: {emoji_of(t)} {t['name']}\n\n"
            "Nom berish uchun shu xabarga javob qilib nom yozing.\n"
            "Rangni o'zgartirish: /color Nom = Rang",
            reply_markup=ForceReply(selective=True, input_field_placeholder="Masalan: Telefonim"),
        )
        if p:
            set_prompt(t["id"], p.chat_id, p.message_id)
        if chat_id not in OWNER_IDS:
            await context.bot.send_message(chat_id, "✅ Joylashuvingiz ulandi.")
    if now - last_ts(t["id"]) >= INTERVAL_MIN * 60 - 5:
        await record(context.bot, t, lat, lon, now)


async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    """Telegram joy o'zgarmasa yangilanish yubormaydi - shunda ham har INTERVAL_MIN da yozib boramiz."""
    now = int(time.time())
    for row in silent_live(now):
        t = dict(row)
        set_alerted(t["id"], True)
        lp = last_point(t["id"])
        where = f"\nOxirgi joy ({datetime.fromtimestamp(lp['ts'], TZ):%H:%M}): {lp['addr']}" if lp else ""
        await notify(context.bot, t, f"⚠️ {emoji_of(t)} {t['name']} dan signal uzildi — "
                                     f"oxirgi yangilanishdan {fmt_dur((now - t['seen']) // 60)} o'tdi.{where}")
    for row in active_live(now):
        t = dict(row)
        if now - t["seen"] > PAUSE_AFTER_H * 3600:  # doimiy ulashish uzilib qolgan bo'lishi mumkin
            set_live(t["id"], t["lat"], t["lon"], t["seen"], -1)
            await notify(
                context.bot, t,
                f"⏸ {emoji_of(t)} {t['name']}: {PAUSE_AFTER_H}+ soatdan beri signal yo'q, kuzatuv pauza qilindi. "
                "Yangilanish kelsa, o'zi davom etadi.",
            )
            continue
        if now - last_ts(t["id"]) >= INTERVAL_MIN * 60 - 5:
            stale = (now - t["seen"]) // 60
            try:
                await record(context.bot, t, t["lat"], t["lon"], now, stale if stale >= 15 else 0)
            except Exception:
                log.exception("heartbeat xato: %s", t["id"])


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«Nom bering» xabariga javob qilib yozilgan nomni qabul qiladi."""
    msg = update.effective_message
    if not allowed(update) or not msg.reply_to_message:
        return
    t = tracker_by_prompt(msg.chat_id, msg.reply_to_message.message_id)
    if not t:
        return
    err = rename_tracker(t["id"], msg.text)
    if err:
        await msg.reply_text(err)
        return
    t = next(x for x in all_trackers() if x["id"] == t["id"])  # yangilangan nom bilan
    await msg.reply_text(f"✅ Nom saqlandi: {emoji_of(t)} {t['name']}")


def arg_pair(context) -> tuple[str, str]:
    name, _, val = " ".join(context.args).partition("=")
    return name.strip(), val.strip()


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    ts = visible_trackers(update.effective_user.id)
    if not ts:
        await update.message.reply_text("Hali jonli joylashuv yo'q. Jonli lokatsiya ulashing.")
        return
    lines = []
    for t in ts:
        cname = next((p[0] for p in PALETTE if p[1] == t["color"].lower()), t["color"])
        lp = last_point(t["id"])
        last = f", oxirgi: {datetime.fromtimestamp(lp['ts'], TZ):%d.%m %H:%M}" if lp else ""
        lines.append(f"{emoji_of(t)} {t['name']} — {cname}{' (to‘xtatilgan)' if t['stopped'] else ''}{last}")
    await update.message.reply_text("\n".join(lines))


async def cmd_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    old, new = arg_pair(context)
    t = find_tracker(update.effective_user.id, old)
    if not (old and new):
        await update.message.reply_text("Format: /rename Eski nom = Yangi nom")
    elif not t:
        await update.message.reply_text(f"«{old}» topilmadi. /list")
    else:
        await update.message.reply_text(rename_tracker(t["id"], new) or f"✅ Nom o'zgardi: {new}")


async def cmd_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    name, color = arg_pair(context)
    t = find_tracker(update.effective_user.id, name)
    if not (name and color):
        await update.message.reply_text("Format: /color Nom = Rang\nRanglar: " + ", ".join(p[0] for p in PALETTE) + " yoki #RRGGBB")
    elif not t:
        await update.message.reply_text(f"«{name}» topilmadi. /list")
    else:
        await update.message.reply_text(set_color(t["id"], color) or "✅ Rang o'zgardi")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    name = " ".join(context.args).strip()
    ts = visible_trackers(update.effective_user.id)
    if name:
        t = find_tracker(update.effective_user.id, name)
        ts = [t] if t else []
        if not t:
            await update.message.reply_text(f"«{name}» topilmadi. /list")
            return
    for t in ts:
        set_stopped(t["id"], True)
    await update.message.reply_text("Kuzatuv to'xtatildi: " + (", ".join(t["name"] for t in ts) or "—") +
                                    "\nQayta boshlash uchun jonli lokatsiyani yangidan ulashing (yangi joylashuv sifatida qo'shiladi).")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.reply_text(
        "Salom! Men jonli lokatsiyalarni kuzataman.\n\n"
        "1) 📎 → Lokatsiya → «Jonli lokatsiyani ulashish». Har bir jonli lokatsiya alohida joylashuv bo'ladi.\n"
        "2) Bot nom so'raydi — javob qilib nom yozing. Har biriga alohida rang beriladi.\n"
        f"3) Har {INTERVAL_MIN} daqiqada manzillarni yozaman, kun oxirida ({SUMMARY_TIME}) hisobot yuboraman.\n\n"
        "/list — joylashuvlar\n/rename Eski = Yangi — nomni o'zgartirish\n/color Nom = Rang — rangni o'zgartirish\n"
        "/stop [Nom] — kuzatuvni to'xtatish\n/app — xarita ilovasi (PWA)\n/today, /yesterday — hisobot"
    )


async def cmd_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    if not (WEB_KEY and PUBLIC_URL):
        await update.message.reply_text("PWA sozlanmagan: .env da WEB_KEY va PUBLIC_URL ni to'ldiring.")
        return
    await update.message.reply_text(
        f"{app_link()}\n\nBu havolani ochib, «Bosh ekranga qo'shish» (Install) ni bosing."
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
    targets = [(o, o) for o in OWNER_IDS] or active_users(day)
    for user_id, chat_id in targets:
        if not day_groups(user_id, day):
            continue
        try:
            await send_summary(context.bot, chat_id, user_id, day)
        except Exception:
            log.exception("kunlik hisobot yuborilmadi: %s", user_id)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    migrate_orphans()
    app = Application.builder().token(BOT_TOKEN).post_init(start_web).post_shutdown(stop_web).build()
    for name, fn in [("start", cmd_start), ("list", cmd_list), ("rename", cmd_rename), ("color", cmd_color),
                     ("stop", cmd_stop), ("app", cmd_app), ("today", cmd_today), ("yesterday", cmd_yesterday)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.job_queue.run_repeating(heartbeat, interval=60, first=30)
    h, m = map(int, SUMMARY_TIME.split(":"))
    app.job_queue.run_daily(daily_job, time=dtime(h, m, tzinfo=TZ))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
