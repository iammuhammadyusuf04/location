#!/usr/bin/env bash
# Ubuntu/Debian serverda (masalan AWS EC2) botni o'rnatadi: Python + systemd xizmati + Caddy (avtomatik HTTPS).
#
# Ishlatish:
#   sudo git clone https://github.com/iammuhammadyusuf04/location /opt/locbot
#   cd /opt/locbot
#   sudo BOT_TOKEN=... ALLOWED_USER_ID=111,222 [WEB_KEY=...] [PWA_URL=https://xxx.netlify.app] \
#        [TZ_NAME=Asia/Tashkent] bash deploy/setup.sh [domen]
#
# domen berilmasa, serverning IP'idan bepul `1-2-3-4.sslip.io` manzili yasaladi.
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "root sifatida ishga tushiring: sudo ..."; exit 1; }
command -v apt-get >/dev/null || { echo "Faqat Ubuntu/Debian qo'llab-quvvatlanadi"; exit 1; }
[ -n "${BOT_TOKEN:-}" ] || { echo "BOT_TOKEN berilmagan"; exit 1; }
if [ -z "${ALLOWED_USER_ID:-}" ]; then
  echo "ALLOWED_USER_ID berilmagan (Telegram ID, @userinfobot dan bilib oling)."
  echo "Bo'sh qoldirilsa bot hamma uchun ochiq bo'lib qoladi, shuning uchun to'xtatildi."
  exit 1
fi
WEB_KEY="${WEB_KEY:-$(openssl rand -hex 24)}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="${1:-}"

# 80/443 portlarni boshqa dastur (masalan, sizning saytingiz: nginx/apache) ishlatayotgan bo'lsa,
# Caddy O'RNATILMAYDI va sayt ishiga tegilmaydi: bot faqat 127.0.0.1:8080 da turadi.
command -v ss >/dev/null || { apt-get update -y >/dev/null && apt-get install -y iproute2 >/dev/null; }
BUSY="$(ss -ltn 2>/dev/null | awk '{print $4}' | grep -E ':(80|443)$' || true)"
if [ -n "${NO_CADDY:-}" ] || { [ -n "$BUSY" ] && ! systemctl is-active --quiet caddy 2>/dev/null; }; then
  USE_CADDY=0
  if [ -z "$DOMAIN" ]; then
    echo "Serverda 80/443 portlarni boshqa dastur (saytingiz) ishlatyapti: Caddy o'rnatilmaydi, saytga tegilmaydi."
    echo "Bot uchun alohida (sub)domen bering va uni shu serverga yo'naltiring, masalan:"
    echo "  sudo BOT_TOKEN=... ALLOWED_USER_ID=... bash deploy/setup.sh bot.sizningsayt.uz"
    exit 1
  fi
else
  USE_CADDY=1
fi

if [ -z "$DOMAIN" ]; then
  IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
  DOMAIN="${IP//./-}.sslip.io"
fi

echo "==> Paketlar o'rnatilmoqda"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip curl gpg debian-keyring debian-archive-keyring apt-transport-https
if [ "$USE_CADDY" = 1 ] && ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y && apt-get install -y caddy
fi

echo "==> Foydalanuvchi va Python muhiti"
id locbot >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin locbot
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> .env yozilmoqda"
[ -f "$APP_DIR/.env" ] && cp "$APP_DIR/.env" "$APP_DIR/.env.bak.$(date +%s)"
umask 077
cat > "$APP_DIR/.env" <<ENV
BOT_TOKEN=$BOT_TOKEN
ALLOWED_USER_ID=$ALLOWED_USER_ID
WEB_KEY=$WEB_KEY
PUBLIC_URL=https://$DOMAIN
PWA_URL=${PWA_URL:-}
TZ=${TZ_NAME:-Asia/Tashkent}
SUMMARY_TIME=23:55
INTERVAL_MIN=10
PORT=8080
WEB_HOST=127.0.0.1
ENV
chown -R locbot:locbot "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo "==> systemd xizmati"
cat > /etc/systemd/system/locbot.service <<UNIT
[Unit]
Description=Location diary Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=locbot
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now locbot
systemctl restart locbot

if [ "$USE_CADDY" = 1 ]; then
  echo "==> Caddy (HTTPS)"
  cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    reverse_proxy 127.0.0.1:8080
}
CADDY
  systemctl enable caddy
  systemctl restart caddy
fi

sleep 3
systemctl --no-pager --lines=8 status locbot || true
cat <<DONE

Tayyor!
  Server manzili : https://$DOMAIN
  WEB_KEY        : $WEB_KEY   (saqlab qo'ying)
  Keyingi qadam  : Telegramda botga /start, so'ng /app yozing.
Loglar : journalctl -u locbot -f
Yangilash: cd $APP_DIR && sudo -u locbot git pull && sudo systemctl restart locbot
DONE

if [ "$USE_CADDY" = 0 ]; then
  cat <<NGINX

Sizning saytingiz 80/443 portlarni ishlatyapti, shuning uchun Caddy o'rnatilmadi (saytga tegilmadi).
Bot 127.0.0.1:8080 da ishlayapti. $DOMAIN ni shu serverga yo'naltirib (DNS A yozuvi),
mavjud nginx ga ALOHIDA fayl sifatida qo'shing (/etc/nginx/conf.d/locbot.conf):

server {
    listen 80;
    server_name $DOMAIN;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
    }
}

so'ng:  sudo nginx -t && sudo systemctl reload nginx && sudo certbot --nginx -d $DOMAIN
NGINX
fi
