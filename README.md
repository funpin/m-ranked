# m-ranked

Read-only monitor for the reaction and view history of Telegram broadcast-channel posts. It stores exact UTC measurements in SQLite, groups Telegram albums into logical posts, calculates deltas, and presents channel and publication ratings in a FastAPI dashboard.

Set `DATA_SOURCE=public_web` to monitor public channels without Telegram credentials. This mode reads Telegram's public, login-free post preview pages. Subscriber counts come from the public channel landing page and are refreshed exactly once a day; post reaction and view counters may be compact values such as `1.2K`. Private channels and the account's subscription list are not available in this mode.

The application never sends messages, reacts, comments, joins channels, or changes the Telegram account. A Telegram user session is as sensitive as a password; keep `data/telegram.session`, `.env`, and the database private.

## Debian 12/13 installation

Run as root. Debian 12 supplies Python 3.11; the code supports Python 3.11 and newer.

```bash
apt-get update
apt-get install -y python3 python3-venv ca-certificates
useradd --system --home /opt/telegram-reaction-monitor --shell /usr/sbin/nologin telegram-monitor || true
mkdir -p /opt/telegram-reaction-monitor/{data,logs}
cd /opt/telegram-reaction-monitor
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
chown -R telegram-monitor:telegram-monitor /opt/telegram-reaction-monitor
```

## Telegram credentials and first authorization

1. Sign in at <https://my.telegram.org>.
2. Open **API development tools** and create an application.
3. Put its numeric `api_id` and `api_hash` in `/opt/telegram-reaction-monitor/.env`.
4. Keep the default session path `/opt/telegram-reaction-monitor/data/telegram.session`.
5. Temporarily give the service account an interactive shell only for authorization, then remove it again:

```bash
usermod -s /bin/bash telegram-monitor
cd /opt/telegram-reaction-monitor
sudo -u telegram-monitor .venv/bin/python -m app auth
usermod -s /usr/sbin/nologin telegram-monitor
chmod 600 data/telegram.session .env
```

Telegram will ask for the phone number, login code, and (when enabled) the account's 2FA password. The saved session is reused after every restart.

## Configure channels and make the first measurement

Channels can be public broadcast-channel usernames or `t.me` URLs. The account must already be able to read them; the monitor never joins them automatically.

```bash
cd /opt/telegram-reaction-monitor
sudo -u telegram-monitor .venv/bin/python -m app add-channel https://t.me/channel_a
sudo -u telegram-monitor .venv/bin/python -m app add-channel @channel_b
sudo -u telegram-monitor .venv/bin/python -m app add-channel @channel_c
sudo -u telegram-monitor .venv/bin/python -m app add-channel @channel_d
sudo -u telegram-monitor .venv/bin/python -m app add-channel @channel_e
sudo -u telegram-monitor .venv/bin/python -m app list-channels
sudo -u telegram-monitor .venv/bin/python -m app poll-now
```

Removing a channel only disables future polling and preserves history:

```bash
sudo -u telegram-monitor .venv/bin/python -m app remove-channel @channel_e
```

## Tests and dashboard smoke test

Tests mock Telegram and do not need credentials or a live session.

```bash
cd /opt/telegram-reaction-monitor
.venv/bin/pytest -q
.venv/bin/python -m app --help
sudo -u telegram-monitor .venv/bin/python -m app web
curl -fsS http://127.0.0.1:8080/health
```

The dashboard binds only to `127.0.0.1:8080`; put nginx or another reverse proxy in front of it.

```bash
ssh -L 8080:127.0.0.1:8080 root@SERVER_IP
```

`/` contains the channel overview, `/rating` contains sortable channel and post ratings, and `/compare` contains two median curves plus an hourly delta heatmap. CSV exports are linked in the navigation bar.

## systemd

```bash
cp deploy/telegram-reaction-monitor.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now telegram-reaction-monitor.service
systemctl status telegram-reaction-monitor.service --no-pager
journalctl -u telegram-reaction-monitor.service -n 100 --no-pager
curl -fsS http://127.0.0.1:8080/health
systemctl restart telegram-reaction-monitor.service
systemctl is-active telegram-reaction-monitor.service
```

The unit uses `Restart=always`, a five-second restart delay, filesystem hardening, and write access only to `data/` and `logs/`.

## Configuration

All persisted timestamps are UTC. `DISPLAY_TIMEZONE` is reserved for display formatting and never changes age calculations.

| Variable | Default | Meaning |
|---|---:|---|
| `POLL_INTERVAL_MINUTES` | `5` | Polling interval for posts younger than 24 hours |
| `TRACK_POST_FOR_HOURS` | `744` | Keep polling posts for 31 days |
| `COMPLETE_HISTORY_MAX_FIRST_AGE_MINUTES` | `6` | Maximum timely first-observation age for complete history |
| `MEDIUM_POLL_INTERVAL_MINUTES` | `15` | Polling interval for posts 1–7 days old |
| `OLD_POLL_INTERVAL_MINUTES` | `180` | Polling interval for posts 7–31 days old |
| `RETENTION_DAYS` | `31` | Archive then remove older live data |
| `SUBSCRIBER_REFRESH_HOURS` | `24` | Exact subscriber refresh interval |
| `JUMP_MIN_ABS` | `15` | Minimum absolute interval jump |
| `JUMP_MIN_RATIO` | `2.0` | Minimum total-reaction ratio |
| `WEB_HOST` | `127.0.0.1` | Dashboard bind address |
| `WEB_PORT` | `8080` | Dashboard port |
| `DISPLAY_TIMEZONE` | `Europe/Moscow` | UI timezone |

After changing `.env`, apply it with:

```bash
systemctl restart telegram-reaction-monitor.service
```

Persistent files:

- SQLite: `/opt/telegram-reaction-monitor/data/reactions.db`
- Compressed per-post archives: `/opt/telegram-reaction-monitor/data/archives/`
- Telegram session: `/opt/telegram-reaction-monitor/data/telegram.session`
- Rotating application log: `/opt/telegram-reaction-monitor/logs/app.log`
- systemd log: `journalctl -u telegram-reaction-monitor.service`

Raw snapshots are append-only. A unique `(post_id, measurement_bucket)` guard prevents duplicate rows on repeated polling while preserving the exact measurement timestamp. Missing intervals are marked uncertain and are never interpolated.
