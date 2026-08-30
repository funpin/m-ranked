from __future__ import annotations

import csv
import io
import json
import math
import os
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..analytics import fixed_cohort_median_curve, hourly_asof_points
from ..config import Settings
from ..collector import normalize_channel_ref
from ..database import Database
from ..m_rating import refresh_m_rating
from ..reactions import custom_emoji_asset
from ..vk import normalize_vk_community_ref


POST_TYPE_LABELS = {
    "text": "текст",
    "photo": "фото",
    "document": "документ",
    "poll": "опрос",
    "webpage": "веб-страница",
    "contact": "контакт",
    "geo": "геолокация",
    "album": "альбом",
    "media": "медиа",
}


def _rows_dict(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _as_datetime(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "—"
    total_minutes = max(0, int(round(float(seconds) / 60)))
    days, remainder = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} д")
    if hours or days:
        parts.append(f"{hours} ч")
    parts.append(f"{minutes} мин")
    return " ".join(parts)


def plural_ru(value: int | float, one: str, few: str, many: str) -> str:
    number = abs(int(value))
    if number % 100 in range(11, 15):
        return many
    if number % 10 == 1:
        return one
    if number % 10 in range(2, 5):
        return few
    return many


def format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if size < 1024 or unit == "ТБ":
            precision = 0 if unit == "Б" else 1
            return f"{size:.{precision}f} {unit}"
        size /= 1024
    return f"{size:.1f} ТБ"


def directory_size(path: Path) -> int:
    total = 0
    for root, directories, files in os.walk(path, followlinks=False):
        directories[:] = [
            name for name in directories if not (Path(root) / name).is_symlink()
        ]
        for name in files:
            try:
                file_path = Path(root) / name
                if not file_path.is_symlink():
                    total += file_path.stat().st_size
            except OSError:
                continue
    return total


def create_app(
    settings: Settings,
    db: Database,
    telegram_connected: Callable[[], bool] | None = None,
) -> FastAPI:
    app = FastAPI(title="m-ranked")
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    tz = ZoneInfo(settings.display_timezone)
    templates.env.filters["local_datetime"] = lambda value: (
        _as_datetime(value).astimezone(tz).strftime("%d.%m.%Y, %H:%M:%S")
        if value else "—"
    )
    templates.env.filters["duration"] = format_duration
    templates.env.filters["plural_ru"] = plural_ru
    basic = HTTPBasic()
    emoji_cache: dict[str, tuple[datetime, bytes, str]] = {}

    def require_admin(credentials: HTTPBasicCredentials = Depends(basic)) -> str:
        if not settings.admin_password:
            raise HTTPException(status_code=503, detail="Пароль администратора не настроен")
        username_ok = secrets.compare_digest(credentials.username, settings.admin_username)
        password_ok = secrets.compare_digest(credentials.password, settings.admin_password)
        if not (username_ok and password_ok):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный логин или пароль",
                headers={"WWW-Authenticate": "Basic"},
            )
        return credentials.username

    def check_csrf(token: str) -> None:
        if not settings.admin_csrf_secret or not secrets.compare_digest(
            token, settings.admin_csrf_secret
        ):
            raise HTTPException(status_code=403, detail="Недействительный защитный токен")

    def render(request: Request, template: str, **context: Any) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name=template,
            context={
                "tz": tz,
                "settings": settings,
                "post_type_labels": POST_TYPE_LABELS,
                **context,
            },
        )

    def period_spec(value: str) -> tuple[str, timedelta, str, str]:
        periods = {
            "3h": (timedelta(hours=3), "Последние 3 часа", "за 3 часа"),
            "1d": (timedelta(days=1), "Последние сутки", "за сутки"),
            "7d": (timedelta(days=7), "Последние 7 дней", "за неделю"),
            "30d": (timedelta(days=30), "Последний месяц", "за месяц"),
        }
        key = value if value in periods else "1d"
        delta, label, short = periods[key]
        return key, delta, label, short

    def channel_period_stats(
        cutoff: datetime, previous_cutoff: datetime | None = None,
    ) -> list[dict[str, Any]]:
        channels = _rows_dict(db.list_channels_with_institutions(enabled_only=True))
        posts = _rows_dict(db.query(
            """SELECT p.id, p.channel_id, p.telegram_message_id, p.history_complete,
               s.total_reactions, s.views_count,
               EXISTS(SELECT 1 FROM reaction_snapshots spike
                      WHERE spike.post_id=p.id AND spike.spike=1) has_spike
               FROM posts p JOIN reaction_snapshots s ON s.id=(
                 SELECT s2.id FROM reaction_snapshots s2
                 WHERE s2.post_id=p.id AND s2.synthetic=0
                 ORDER BY s2.measured_at DESC LIMIT 1)
               WHERE p.published_at>=?""",
            (cutoff.isoformat(),),
        ))
        grouped: dict[int, list[dict[str, Any]]] = {}
        for post in posts:
            grouped.setdefault(int(post["channel_id"]), []).append(post)
        previous_grouped: dict[int, list[dict[str, Any]]] = {}
        if previous_cutoff is not None:
            previous_posts = _rows_dict(db.query(
                """SELECT p.channel_id, s.total_reactions, s.views_count
                   FROM posts p JOIN reaction_snapshots s ON s.id=(
                     SELECT s2.id FROM reaction_snapshots s2
                     WHERE s2.post_id=p.id AND s2.synthetic=0
                     ORDER BY s2.measured_at DESC LIMIT 1)
                   WHERE p.published_at>=? AND p.published_at<?""",
                (previous_cutoff.isoformat(), cutoff.isoformat()),
            ))
            for post in previous_posts:
                previous_grouped.setdefault(int(post["channel_id"]), []).append(post)
        trend_rows = _rows_dict(db.query(
            """SELECT p.id, p.channel_id, p.published_at,
               p.baseline_from_publication, latest.measured_at,
               latest.total_reactions, latest.views_count,
               (SELECT b.total_reactions FROM reaction_snapshots b
                WHERE b.post_id=p.id AND b.synthetic=0 AND b.measured_at<=?
                ORDER BY b.measured_at DESC LIMIT 1) base_reactions,
               (SELECT b.views_count FROM reaction_snapshots b
                WHERE b.post_id=p.id AND b.synthetic=0 AND b.measured_at<=?
                ORDER BY b.measured_at DESC LIMIT 1) base_views,
               (SELECT f.total_reactions FROM reaction_snapshots f
                WHERE f.post_id=p.id AND f.synthetic=0 AND f.measured_at>?
                ORDER BY f.measured_at LIMIT 1) first_reactions,
               (SELECT f.views_count FROM reaction_snapshots f
                WHERE f.post_id=p.id AND f.synthetic=0 AND f.measured_at>?
                ORDER BY f.measured_at LIMIT 1) first_views
               FROM posts p JOIN reaction_snapshots latest ON latest.id=(
                 SELECT s2.id FROM reaction_snapshots s2
                 WHERE s2.post_id=p.id AND s2.synthetic=0
                 ORDER BY s2.measured_at DESC LIMIT 1)
               WHERE latest.measured_at>=? AND p.published_at>=?""",
            (cutoff.isoformat(), cutoff.isoformat(), cutoff.isoformat(),
             cutoff.isoformat(), cutoff.isoformat(), cutoff.isoformat()),
        ))
        trends: dict[int, dict[str, int]] = {}
        for row in trend_rows:
            published = _as_datetime(row["published_at"])
            if published >= cutoff and bool(row["baseline_from_publication"]):
                base_reactions, base_views = 0, 0
            else:
                base_reactions = row["base_reactions"]
                base_views = row["base_views"]
                if base_reactions is None:
                    base_reactions = row["first_reactions"]
                if base_views is None:
                    base_views = row["first_views"]
            trend = trends.setdefault(int(row["channel_id"]), {"reactions": 0, "views": 0})
            if base_reactions is not None:
                trend["reactions"] += int(row["total_reactions"] or 0) - int(base_reactions)
            if row["views_count"] is not None and base_views is not None:
                trend["views"] += int(row["views_count"]) - int(base_views)
        result: list[dict[str, Any]] = []
        for channel in channels:
            measured = grouped.get(int(channel["id"]), [])
            reactions = [int(post["total_reactions"] or 0) for post in measured]
            views = [int(post["views_count"]) for post in measured if post["views_count"] is not None]
            previous_measured = previous_grouped.get(int(channel["id"]), [])
            previous_reactions = [
                int(post["total_reactions"] or 0) for post in previous_measured
            ]
            previous_views = [
                int(post["views_count"])
                for post in previous_measured if post["views_count"] is not None
            ]
            subscribers = channel.get("subscriber_count")
            average = sum(reactions) / len(reactions) if reactions else 0.0
            current_median_reactions = median(reactions) if reactions else None
            current_median_views = median(views) if views else None
            previous_median_reactions = median(previous_reactions) if previous_reactions else None
            previous_median_views = median(previous_views) if previous_views else None
            # A mathematical median can end in .5 when there is an even
            # number of posts. Counts themselves cannot be fractional, so the
            # dashboard exposes the nearest whole count and compares those
            # same displayed values between periods.
            display_median_reactions = (
                math.floor(current_median_reactions + 0.5)
                if current_median_reactions is not None else None
            )
            display_median_views = (
                math.floor(current_median_views + 0.5)
                if current_median_views is not None else None
            )
            previous_display_median_reactions = (
                math.floor(previous_median_reactions + 0.5)
                if previous_median_reactions is not None else None
            )
            previous_display_median_views = (
                math.floor(previous_median_views + 0.5)
                if previous_median_views is not None else None
            )
            channel.update({
                "post_count": len(measured),
                "complete_count": sum(bool(post["history_complete"]) for post in measured),
                "spike_posts": sum(bool(post["has_spike"]) for post in measured),
                "total_reactions": sum(reactions),
                "avg_reactions": average,
                "median_reactions": display_median_reactions,
                "total_views": sum(views),
                "median_views": display_median_views,
                "delta_median_reactions": (
                    display_median_reactions - previous_display_median_reactions
                    if display_median_reactions is not None
                    and previous_display_median_reactions is not None else None
                ),
                "delta_median_views": (
                    display_median_views - previous_display_median_views
                    if display_median_views is not None
                    and previous_display_median_views is not None else None
                ),
                "engagement": (
                    average * 100 / int(subscribers)
                    if subscribers and int(subscribers) > 0 else None
                ),
                "delta_reactions": trends.get(int(channel["id"]), {}).get("reactions", 0),
                "delta_views": trends.get(int(channel["id"]), {}).get("views", 0),
            })
            result.append(channel)
        return result

    def channel_activity_stats(
        cutoff: datetime, previous_cutoff: datetime,
    ) -> list[dict[str, Any]]:
        """Aggregate actual post changes during a time window for the overview."""

        now = datetime.now(timezone.utc)
        channels = _rows_dict(db.list_channels_with_institutions(enabled_only=True))

        def window_samples(start: datetime, end: datetime) -> dict[int, list[dict[str, Any]]]:
            rows = _rows_dict(db.query(
                """SELECT p.id, p.channel_id, p.published_at, p.baseline_from_publication,
                   latest.id AS latest_snapshot_id,
                   latest.total_reactions, latest.views_count,
                   (SELECT f.id FROM reaction_snapshots f
                    WHERE f.post_id=p.id AND f.synthetic=0 AND f.measured_at>? AND f.measured_at<=?
                    ORDER BY f.measured_at LIMIT 1) first_snapshot_id,
                   (SELECT f.total_reactions FROM reaction_snapshots f
                    WHERE f.post_id=p.id AND f.synthetic=0 AND f.measured_at>? AND f.measured_at<=?
                    ORDER BY f.measured_at LIMIT 1) first_reactions,
                   (SELECT f.views_count FROM reaction_snapshots f
                    WHERE f.post_id=p.id AND f.synthetic=0 AND f.measured_at>? AND f.measured_at<=?
                    ORDER BY f.measured_at LIMIT 1) first_views
                   FROM posts p JOIN reaction_snapshots latest ON latest.id=(
                     SELECT s.id FROM reaction_snapshots s
                     WHERE s.post_id=p.id AND s.synthetic=0
                       AND s.measured_at>? AND s.measured_at<=?
                     ORDER BY s.measured_at DESC LIMIT 1)
                   WHERE p.published_at<=?""",
                (
                    start.isoformat(), end.isoformat(),
                    start.isoformat(), end.isoformat(),
                    start.isoformat(), end.isoformat(),
                    start.isoformat(), end.isoformat(),
                    end.isoformat(),
                ),
            ))
            grouped: dict[int, list[dict[str, Any]]] = {}
            for row in rows:
                published = _as_datetime(row["published_at"])
                from_publication = published >= start and bool(row["baseline_from_publication"])
                has_measured_interval = (
                    row["first_snapshot_id"] is not None
                    and int(row["first_snapshot_id"]) != int(row["latest_snapshot_id"])
                )
                base_reactions = (
                    0 if from_publication
                    else row["first_reactions"] if has_measured_interval else None
                )
                base_views = (
                    0 if from_publication
                    else row["first_views"] if has_measured_interval else None
                )
                row["reaction_delta"] = (
                    int(row["total_reactions"] or 0) - int(base_reactions)
                    if base_reactions is not None else None
                )
                row["view_delta"] = (
                    int(row["views_count"]) - int(base_views)
                    if row["views_count"] is not None and base_views is not None else None
                )
                if row["reaction_delta"] is not None or row["view_delta"] is not None:
                    grouped.setdefault(int(row["channel_id"]), []).append(row)
            return grouped

        current = window_samples(cutoff, now)
        previous = window_samples(previous_cutoff, cutoff)
        newly_published = _rows_dict(db.query(
            """SELECT channel_id, COUNT(*) AS post_count
               FROM posts WHERE published_at>=? AND published_at<=?
               GROUP BY channel_id""",
            (cutoff.isoformat(), now.isoformat()),
        ))
        new_count_by_channel = {
            int(row["channel_id"]): int(row["post_count"])
            for row in newly_published
        }
        all_posts = _rows_dict(db.query(
            """SELECT channel_id, COUNT(*) AS post_count
               FROM posts GROUP BY channel_id"""
        ))
        total_count_by_channel = {
            int(row["channel_id"]): int(row["post_count"])
            for row in all_posts
        }

        def rounded_median(values: list[int]) -> int | None:
            return math.floor(median(values) + 0.5) if values else None

        result: list[dict[str, Any]] = []
        for channel in channels:
            channel_id = int(channel["id"])
            samples = current.get(channel_id, [])
            previous_samples = previous.get(channel_id, [])
            reactions = [
                int(row["reaction_delta"])
                for row in samples if row["reaction_delta"] is not None
            ]
            views = [
                int(row["view_delta"])
                for row in samples if row["view_delta"] is not None
            ]
            previous_reactions = [
                int(row["reaction_delta"])
                for row in previous_samples if row["reaction_delta"] is not None
            ]
            previous_views = [
                int(row["view_delta"])
                for row in previous_samples if row["view_delta"] is not None
            ]
            median_reactions = rounded_median(reactions)
            median_views = rounded_median(views)
            previous_median_reactions = rounded_median(previous_reactions)
            previous_median_views = rounded_median(previous_views)
            total_reactions = sum(reactions) if reactions else None
            total_views = sum(views) if views else None
            previous_total_reactions = (
                sum(previous_reactions) if previous_reactions else None
            )
            previous_total_views = sum(previous_views) if previous_views else None
            channel.update({
                "total_post_count": total_count_by_channel.get(channel_id, 0),
                "post_count": new_count_by_channel.get(channel_id, 0),
                "activity_post_count": len(samples),
                "total_reactions": total_reactions,
                "total_views": total_views,
                "median_reactions": median_reactions,
                "median_views": median_views,
                "delta_total_reactions": (
                    total_reactions - previous_total_reactions
                    if total_reactions is not None
                    and previous_total_reactions is not None else None
                ),
                "delta_total_views": (
                    total_views - previous_total_views
                    if total_views is not None
                    and previous_total_views is not None else None
                ),
                "delta_median_reactions": (
                    median_reactions - previous_median_reactions
                    if median_reactions is not None
                    and previous_median_reactions is not None else None
                ),
                "delta_median_views": (
                    median_views - previous_median_views
                    if median_views is not None and previous_median_views is not None else None
                ),
            })
            result.append(channel)
        return result

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "data_source": settings.data_source,
            "source_connected": bool(telegram_connected and telegram_connected()),
            "telegram_connected": (
                bool(telegram_connected and telegram_connected())
                if settings.data_source == "mtproto" else False
            ),
            "channels": len(db.list_channels(enabled_only=True)),
            "last_poll": db.get_state("last_poll"),
            "next_poll": db.get_state("next_poll"),
            "poll_cycle": {
                "started_at": db.get_state("poll_last_started_at"),
                "completed_at": db.get_state("poll_last_completed_at"),
                "duration_seconds": db.get_state("poll_last_duration_seconds"),
                "error_count": db.get_state("poll_last_error_count"),
                "channel_count": db.get_state("poll_last_channel_count"),
            },
        }

    @app.get("/emoji/{emoji_id}")
    async def custom_emoji(emoji_id: str) -> Response:
        if not emoji_id.isdigit() or len(emoji_id) > 32:
            raise HTTPException(status_code=404, detail="Реакция не найдена")
        cached = emoji_cache.get(emoji_id)
        now = datetime.now(timezone.utc)
        if cached and cached[0] > now:
            return Response(
                cached[1], media_type=cached[2],
                headers={"Cache-Control": "public, max-age=21600"},
            )
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(f"https://t.me/i/emoji/{emoji_id}.json")
            if response.status_code != 200:
                raise HTTPException(status_code=404, detail="Реакция не найдена")
            payload = response.json()
            target = custom_emoji_asset(payload) or ""
            hostname = (urlparse(target).hostname or "").lower()
            if not target.startswith("https://") or not (
                hostname == "t.me"
                or hostname.endswith(".telegram.org")
                or hostname.endswith(".telesco.pe")
            ):
                raise HTTPException(status_code=404, detail="Реакция не найдена")
            image_response = await client.get(target)
            if image_response.status_code != 200 or len(image_response.content) > 2_000_000:
                raise HTTPException(status_code=404, detail="Реакция не найдена")
        response_type = image_response.headers.get("content-type", "").split(";", 1)[0]
        allowed_types = {"image/webp", "image/png", "image/gif", "image/jpeg"}
        media_type = response_type if response_type in allowed_types else "image/webp"
        emoji_cache[emoji_id] = (now + timedelta(hours=6), image_response.content, media_type)
        return Response(
            image_response.content, media_type=media_type,
            headers={"Cache-Control": "public, max-age=21600"},
        )

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        period: str = Query(default="1d"),
        sort: str = Query(default="median_reactions"),
        direction: str = Query(default="desc"),
    ) -> HTMLResponse:
        period, period_delta, period_label, period_short = period_spec(period)
        cutoff = datetime.now(timezone.utc) - period_delta
        sort_keys = {
            "subscribers": "subscriber_count", "posts": "post_count",
            "views": "total_views", "reactions": "total_reactions",
            "median_reactions": "median_reactions",
            "m_rating": "m_rating_tg_rank",
        }
        sort = sort if sort in sort_keys else "median_reactions"
        direction = direction if direction in {"asc", "desc"} else "desc"
        channels = channel_activity_stats(cutoff, cutoff - period_delta)
        sort_key = sort_keys[sort]
        available = [row for row in channels if row.get(sort_key) is not None]
        unavailable = [row for row in channels if row.get(sort_key) is None]
        available.sort(
            key=lambda row: row[sort_key], reverse=direction == "desc",
        )
        channels = available + unavailable
        return render(
            request, "overview.html", channels=channels, period=period,
            period_label=period_label, period_short=period_short,
            sort=sort, direction=direction,
        )

    @app.get("/rating", response_class=HTMLResponse)
    async def rating(
        request: Request,
        period: str = Query(default="30d"),
        channel_sort: str = Query(default="engagement"),
        channel_direction: str = Query(default="desc"),
        post_sort: str = Query(default="view_share"),
        post_direction: str = Query(default="desc"),
    ) -> HTMLResponse:
        period, period_delta, period_label, period_short = period_spec(period)
        channel_keys = {
            "average": "avg_reactions", "total": "total_reactions",
            "engagement": "engagement", "subscribers": "subscriber_count",
        }
        channel_sort = channel_sort if channel_sort in channel_keys else "engagement"
        channel_direction = channel_direction if channel_direction in {"asc", "desc"} else "desc"
        cutoff = datetime.now(timezone.utc) - period_delta
        channel_rankings = channel_period_stats(cutoff)
        channel_rankings.sort(
            key=lambda row: (
                row.get(channel_keys[channel_sort]) is not None,
                row.get(channel_keys[channel_sort]) or 0,
            ),
            reverse=channel_direction == "desc",
        )
        top_posts = _rows_dict(db.query(
            """SELECT p.id, p.telegram_message_id, p.deleted_at, c.username, c.title,
                 c.subscriber_count, s.total_reactions, s.views_count,
                 CASE WHEN c.subscriber_count>0
                   THEN s.total_reactions*100.0/c.subscriber_count ELSE NULL END engagement,
                 CASE WHEN s.views_count>0
                   THEN s.total_reactions*100.0/s.views_count ELSE NULL END view_engagement
               FROM posts p JOIN channels c ON c.id=p.channel_id
               JOIN reaction_snapshots s ON s.id=(
                 SELECT s2.id FROM reaction_snapshots s2
                 WHERE s2.post_id=p.id AND s2.synthetic=0
                 ORDER BY s2.measured_at DESC LIMIT 1)
               WHERE c.enabled=1 AND p.published_at>=?""",
            (cutoff.isoformat(),),
        ))
        post_keys = {
            "reactions": "total_reactions", "subscriber_share": "engagement",
            "view_share": "view_engagement", "views": "views_count",
        }
        post_sort = post_sort if post_sort in post_keys else "reactions"
        post_direction = post_direction if post_direction in {"asc", "desc"} else "desc"
        top_posts.sort(
            key=lambda row: (
                row.get(post_keys[post_sort]) is not None,
                row.get(post_keys[post_sort]) or 0,
            ),
            reverse=post_direction == "desc",
        )
        return render(
            request, "index.html", channel_rankings=channel_rankings,
            top_posts=top_posts[:50], period=period, period_label=period_label,
            period_short=period_short,
            period_badge={"3h": "3 часа", "1d": "24 часа", "7d": "7 дней", "30d": "30 дней"}[period],
            channel_sort=channel_sort,
            channel_direction=channel_direction, post_sort=post_sort,
            post_direction=post_direction,
        )

    @app.get("/manage", response_class=HTMLResponse)
    async def manage(
        request: Request,
        m_rating_status: str | None = Query(default=None),
        channel_status: str | None = Query(default=None),
        platform_status: str | None = Query(default=None),
        _: str = Depends(require_admin),
    ) -> HTMLResponse:
        managed_channels = db.list_channels_with_institutions()
        institutions = db.list_institutions()
        platform_accounts = db.list_platform_accounts()
        accounts_by_institution: dict[int, list[Any]] = {}
        for account in platform_accounts:
            accounts_by_institution.setdefault(int(account["institution_id"]), []).append(account)
        institution_groups = [
            {"institution": institution,
             "accounts": accounts_by_institution.get(int(institution["id"]), [])}
            for institution in institutions
        ]
        project_root = Path(__file__).resolve().parents[2]
        database_path = settings.database_path
        if not database_path.is_absolute():
            database_path = project_root / database_path
        disk = shutil.disk_usage(project_root)
        project_bytes = directory_size(project_root)
        database_bytes = database_path.stat().st_size if database_path.exists() else 0
        storage = {
            "disk_used": format_bytes(disk.used),
            "disk_total": format_bytes(disk.total),
            "disk_free": format_bytes(disk.free),
            "disk_percent": round(disk.used * 100 / disk.total, 1) if disk.total else 0,
            "project_size": format_bytes(project_bytes),
            "project_percent": round(project_bytes * 100 / disk.used, 2) if disk.used else 0,
            "database_size": format_bytes(database_bytes),
            "database_percent": (
                round(database_bytes * 100 / project_bytes, 2) if project_bytes else 0
            ),
        }
        return render(
            request, "manage.html", channels=managed_channels,
            channel_count=len(managed_channels),
            institutions=institutions,
            institution_names={row["id"]: row["name"] for row in institutions},
            institution_groups=institution_groups,
            platform_accounts=platform_accounts,
            platform_count=len(platform_accounts),
            platform_status=platform_status,
            storage=storage,
            csrf_token=settings.admin_csrf_secret,
            m_rating_status=m_rating_status,
            channel_status=channel_status,
            m_rating_period=db.get_state("m_rating_last_period"),
            m_rating_updated=db.get_state("m_rating_last_updated"),
            m_rating_error=db.get_state("m_rating_last_error"),
        )

    @app.post("/manage/m-rating/update")
    async def manage_update_m_rating(
        csrf_token: str = Form(...),
        _: str = Depends(require_admin),
    ) -> RedirectResponse:
        check_csrf(csrf_token)
        try:
            await refresh_m_rating(db)
        except Exception:
            return RedirectResponse("/manage?m_rating_status=error", status_code=303)
        return RedirectResponse("/manage?m_rating_status=updated", status_code=303)

    @app.post("/manage/channels")
    async def manage_add_channel(
        channel: str = Form(...), csrf_token: str = Form(...),
        _: str = Depends(require_admin),
    ) -> RedirectResponse:
        check_csrf(csrf_token)
        try:
            db.add_channel(normalize_channel_ref(channel))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse("/manage?channel_status=added", status_code=303)

    @app.post("/manage/institutions")
    async def manage_add_institution(
        name: str = Form(...), short_name: str = Form(default=""),
        csrf_token: str = Form(...), _: str = Depends(require_admin),
    ) -> RedirectResponse:
        check_csrf(csrf_token)
        if not name.strip():
            raise HTTPException(status_code=400, detail="Укажите название вуза")
        db.add_institution(name, short_name or None)
        return RedirectResponse("/manage?platform_status=institution-added", status_code=303)

    @app.post("/manage/institutions/{institution_id}")
    async def manage_update_institution(
        institution_id: int, name: str = Form(...), short_name: str = Form(...),
        csrf_token: str = Form(...), _: str = Depends(require_admin),
    ) -> RedirectResponse:
        check_csrf(csrf_token)
        try:
            updated = db.update_institution(institution_id, name, short_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="Вуз не найден")
        return RedirectResponse("/manage?platform_status=institution-updated", status_code=303)

    @app.post("/manage/institutions/{institution_id}/accounts")
    async def manage_update_institution_accounts(
        institution_id: int, telegram: str = Form(default=""),
        vk: str = Form(default=""), max_account: str = Form(default=""),
        rutube: str = Form(default=""), csrf_token: str = Form(...),
        _: str = Depends(require_admin),
    ) -> RedirectResponse:
        check_csrf(csrf_token)
        if institution_id not in {int(row["id"]) for row in db.list_institutions()}:
            raise HTTPException(status_code=404, detail="Вуз не найден")
        values = {"telegram": telegram, "vk": vk, "max": max_account, "rutube": rutube}
        if not any(value.strip() for value in values.values()):
            raise HTTPException(status_code=400, detail="Укажите хотя бы один аккаунт")
        for platform, reference in values.items():
            original = reference.strip()
            if not original:
                continue
            if platform == "telegram":
                db.add_channel(normalize_channel_ref(original), institution_id=institution_id)
                continue
            if platform == "vk":
                external_key = normalize_vk_community_ref(original)
                account_url = f"https://vk.com/{external_key}"
                access_mode, data_quality = "public", "exact"
            else:
                parsed = urlparse(original if "://" in original else f"https://placeholder/{original}")
                if "://" in original and (
                    parsed.scheme not in {"http", "https"} or not parsed.hostname
                ):
                    raise HTTPException(status_code=400, detail=f"Некорректная ссылка {platform}")
                external_key = parsed.path.strip("/").split("/")[-1].lstrip("@")
                if not external_key:
                    raise HTTPException(status_code=400, detail=f"Не удалось определить {platform}")
                account_url = original if "://" in original else None
                access_mode, data_quality = "owner", "unavailable"
            db.add_platform_account(
                institution_id, platform, external_key, username=external_key,
                url=account_url, access_mode=access_mode, data_quality=data_quality,
            )
        return RedirectResponse("/manage?platform_status=accounts-updated", status_code=303)

    @app.post("/manage/platform-accounts")
    async def manage_add_platform_account(
        institution_id: int = Form(...), platform: str = Form(...),
        reference: str = Form(...), title: str = Form(default=""),
        url: str = Form(default=""), csrf_token: str = Form(...),
        _: str = Depends(require_admin),
    ) -> RedirectResponse:
        check_csrf(csrf_token)
        if platform not in {"vk", "max", "rutube"}:
            raise HTTPException(
                status_code=400,
                detail="Telegram-каналы добавляются через основную форму мониторинга",
            )
        institutions = {int(row["id"]) for row in db.list_institutions()}
        if institution_id not in institutions:
            raise HTTPException(status_code=404, detail="Вуз не найден")
        original = reference.strip()
        if not original:
            raise HTTPException(status_code=400, detail="Укажите аккаунт или ссылку")
        if platform == "vk":
            external_key = normalize_vk_community_ref(original)
            username = external_key
            account_url = url.strip() or f"https://vk.com/{external_key}"
            access_mode, data_quality = "public", "exact"
        else:
            parsed = urlparse(original if "://" in original else f"https://placeholder/{original}")
            if "://" in original and (
                parsed.scheme not in {"http", "https"} or not parsed.hostname
            ):
                raise HTTPException(status_code=400, detail=f"Некорректная ссылка {platform}")
            external_key = parsed.path.strip("/").split("/")[-1].lstrip("@")
            if not external_key:
                raise HTTPException(status_code=400, detail="Не удалось определить аккаунт")
            username = external_key
            account_url = url.strip() or (original if "://" in original else None)
            access_mode, data_quality = "owner", "unavailable"
        db.add_platform_account(
            institution_id, platform, external_key, username=username,
            title=title.strip() or None, url=account_url,
            access_mode=access_mode, data_quality=data_quality,
        )
        return RedirectResponse("/manage?platform_status=account-added", status_code=303)

    @app.post("/manage/channels/{channel_id}/disable")
    async def manage_disable_channel(
        channel_id: int, csrf_token: str = Form(...),
        _: str = Depends(require_admin),
    ) -> RedirectResponse:
        check_csrf(csrf_token)
        channel = db.channel(channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Канал не найден")
        db.disable_channel(str(channel["username"]))
        return RedirectResponse("/manage", status_code=303)

    @app.post("/manage/channels/{channel_id}/enable")
    async def manage_enable_channel(
        channel_id: int, csrf_token: str = Form(...),
        _: str = Depends(require_admin),
    ) -> RedirectResponse:
        check_csrf(csrf_token)
        channel = db.channel(channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Канал не найден")
        db.add_channel(str(channel["username"]))
        return RedirectResponse("/manage", status_code=303)

    @app.post("/manage/channels/{channel_id}/delete")
    async def manage_delete_channel(
        channel_id: int, csrf_token: str = Form(...),
        _: str = Depends(require_admin),
    ) -> RedirectResponse:
        check_csrf(csrf_token)
        if not db.delete_channel(channel_id):
            raise HTTPException(status_code=404, detail="Канал не найден")
        return RedirectResponse("/manage?channel_status=deleted", status_code=303)

    @app.get("/channels/{channel_id}", response_class=HTMLResponse)
    async def channel_page(request: Request, channel_id: int) -> HTMLResponse:
        channel = db.channel(channel_id)
        if channel is None:
            return HTMLResponse("Канал не найден", status_code=404)
        retention_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
        posts = db.query(
            """SELECT p.*,
                (SELECT total_reactions FROM reaction_snapshots s WHERE s.post_id=p.id ORDER BY measured_at DESC LIMIT 1) current_total,
                (SELECT max(delta_total) FROM reaction_snapshots s WHERE s.post_id=p.id) max_jump,
                (SELECT max(age_seconds) FROM reaction_snapshots s WHERE s.post_id=p.id) current_age,
                (SELECT views_count FROM reaction_snapshots s WHERE s.post_id=p.id
                 ORDER BY measured_at DESC LIMIT 1) current_views,
                (SELECT comments_count FROM reaction_snapshots s WHERE s.post_id=p.id
                 ORDER BY measured_at DESC LIMIT 1) current_comments,
                (SELECT max(spike) FROM reaction_snapshots s WHERE s.post_id=p.id) has_spike
               FROM posts p WHERE p.channel_id=? AND p.published_at>=?
               ORDER BY p.published_at DESC""",
            (channel_id, retention_cutoff.isoformat()),
        )
        spike_stats = db.query(
            """SELECT count(DISTINCT p.id) monitored,
                count(DISTINCT CASE WHEN s.spike=1 THEN p.id END) with_spike
               FROM posts p LEFT JOIN reaction_snapshots s ON s.post_id=p.id
               WHERE p.channel_id=? AND p.published_at>=? AND p.history_complete=1""",
            (channel_id, retention_cutoff.isoformat()),
        )[0]
        spikes = db.query(
            """SELECT s.age_seconds, s.delta_total FROM reaction_snapshots s
               JOIN posts p ON p.id=s.post_id
               WHERE p.channel_id=? AND p.published_at>=? AND p.history_complete=1 AND s.spike=1""",
            (channel_id, retention_cutoff.isoformat()),
        )
        latest_metrics = db.query(
            """SELECT s.views_count, s.comments_count, s.total_reactions FROM posts p
               JOIN reaction_snapshots s ON s.id=(
                 SELECT s2.id FROM reaction_snapshots s2
                 WHERE s2.post_id=p.id AND s2.synthetic=0
                 ORDER BY s2.measured_at DESC LIMIT 1)
               WHERE p.channel_id=? AND p.published_at>=?""",
            (channel_id, retention_cutoff.isoformat()),
        )
        stats = dict(spike_stats)
        stats["post_count"] = len(posts)
        stats["rate"] = 100 * stats["with_spike"] / stats["monitored"] if stats["monitored"] else 0
        stats["median_age"] = median([row["age_seconds"] for row in spikes]) if spikes else None
        stats["median_size"] = median([row["delta_total"] for row in spikes]) if spikes else None
        views = [row["views_count"] for row in latest_metrics if row["views_count"] is not None]
        reactions = [row["total_reactions"] for row in latest_metrics]
        stats["median_views"] = median(views) if views else None
        stats["median_reactions"] = median(reactions) if reactions else None
        comments = [row["comments_count"] for row in latest_metrics if row["comments_count"] is not None]
        stats["median_comments"] = median(comments) if comments else None
        stats["retention_days"] = settings.retention_days
        return render(request, "channel.html", channel=channel, posts=posts, stats=stats)

    @app.get("/posts/{post_id}", response_class=HTMLResponse)
    async def post_page(request: Request, post_id: int) -> HTMLResponse:
        found = db.query(
            """SELECT p.*, c.username, c.title FROM posts p
               JOIN channels c ON c.id=p.channel_id WHERE p.id=?""",
            (post_id,),
        )
        if not found:
            return HTMLResponse("Публикация не найдена", status_code=404)
        post = found[0]
        older_post = db.query(
            """SELECT id, telegram_message_id FROM posts
               WHERE channel_id=? AND (published_at<? OR (published_at=? AND id<?))
               ORDER BY published_at DESC, id DESC LIMIT 1""",
            (post["channel_id"], post["published_at"], post["published_at"], post_id),
        )
        newer_post = db.query(
            """SELECT id, telegram_message_id FROM posts
               WHERE channel_id=? AND (published_at>? OR (published_at=? AND id>?))
               ORDER BY published_at ASC, id ASC LIMIT 1""",
            (post["channel_id"], post["published_at"], post["published_at"], post_id),
        )
        snapshots = _rows_dict(db.query(
            "SELECT * FROM reaction_snapshots WHERE post_id=? ORDER BY measured_at", (post_id,)
        ))
        for row in snapshots:
            row["reactions"] = json.loads(row["reactions_json"])
            row["delta_reactions"] = json.loads(row["delta_by_reaction_json"] or "{}")
            row["minimum_people"] = (
                math.ceil(int(row["delta_total"]) / 3)
                if row["delta_total"] is not None and int(row["delta_total"]) > 0
                else (0 if row["delta_total"] is not None else None)
            )
            row["measured_label"] = _as_datetime(row["measured_at"]).astimezone(tz).strftime(
                "%d.%m, %H:%M:%S"
            )
            row["age_label"] = (
                "момент публикации" if row.get("synthetic") else
                f"через {format_duration(row['age_seconds'])}"
            )
        return render(
            request, "post.html", post=post, snapshots=snapshots,
            older_post=older_post[0] if older_post else None,
            newer_post=newer_post[0] if newer_post else None,
            chart_json=json.dumps(snapshots, ensure_ascii=False),
        )

    @app.get("/compare", response_class=HTMLResponse)
    async def compare(
        request: Request,
        channels: list[int] = Query(default=[]),
        period: int = Query(default=72),
        include_partial: bool = Query(default=False),
        submitted: bool = Query(default=False),
    ) -> HTMLResponse:
        all_channels = sorted(
            db.list_channels(enabled_only=True),
            key=lambda row: str(row["title"] or row["username"]).casefold(),
        )
        selected = channels if submitted else [int(row["id"]) for row in all_channels]
        period = period if period in (24, 48, 72, 168, 336) else 72
        datasets: list[dict[str, Any]] = []
        for channel in all_channels:
            if channel["id"] not in selected:
                continue
            partial_sql = "" if include_partial else "AND p.history_complete=1"
            posts = db.query(
                f"""SELECT p.id, p.telegram_message_id, p.deleted_at FROM posts p
                    WHERE p.channel_id=? {partial_sql}
                      AND EXISTS(SELECT 1 FROM reaction_snapshots coverage
                                 WHERE coverage.post_id=p.id AND coverage.age_seconds>=?)""",
                (channel["id"], period * 3600),
            )
            raw_points: list[dict[int, float]] = []
            raw_conversion_points: list[dict[int, float]] = []
            for post in posts:
                rows = db.query(
                    """SELECT age_seconds, total_reactions, views_count
                       FROM reaction_snapshots WHERE post_id=? AND age_seconds<=? ORDER BY age_seconds""",
                    (post["id"], period * 3600),
                )
                points = hourly_asof_points(rows, period)
                if points:
                    raw_points.append(points)
                conversion_rows = [
                    {
                        "age_seconds": row["age_seconds"],
                        "total_reactions": (
                            float(row["total_reactions"] or 0)
                            * 100 / float(row["views_count"])
                        ),
                    }
                    for row in rows
                    if row["views_count"] is not None and int(row["views_count"]) > 0
                ]
                conversion_points = hourly_asof_points(conversion_rows, period)
                if conversion_points:
                    raw_conversion_points.append(conversion_points)
            start_hour = 1 if include_partial else 0
            curve, sample_counts, cohort_size = fixed_cohort_median_curve(
                raw_points, period, start_hour=start_hour,
            )
            conversion_curve, conversion_sample_counts, conversion_cohort_size = (
                fixed_cohort_median_curve(raw_conversion_points, period, start_hour=1)
            )
            datasets.append({
                "channel": channel["username"],
                "title": channel["title"] or f"@{channel['username']}",
                "curve": curve,
                "sample_counts": sample_counts,
                "cohort_size": cohort_size,
                "conversion_curve": conversion_curve,
                "conversion_sample_counts": conversion_sample_counts,
                "conversion_cohort_size": conversion_cohort_size,
            })
        data = {"labels": list(range(period + 1)), "datasets": datasets}
        has_points = any(
            any(value is not None for value in dataset["curve"])
            for dataset in datasets
        )
        return render(
            request, "compare.html", channels=all_channels, selected=selected, period=period,
            comparison_period_label={
                24: "24 часа", 48: "48 часов", 72: "72 часа",
                168: "7 дней", 336: "14 дней",
            }[period],
            include_partial=include_partial, data_json=json.dumps(data),
            has_points=has_points, submitted=submitted,
        )

    def csv_response(name: str, headers: list[str], rows: list[list[Any]]) -> StreamingResponse:
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)
        return StreamingResponse(
            iter([stream.getvalue()]), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/export/snapshots.csv")
    async def export_snapshots() -> StreamingResponse:
        rows = db.query(
            """SELECT c.username, p.telegram_message_id, p.published_at, s.measured_at,
               s.age_seconds/3600.0 age_hours, s.total_reactions, s.delta_total,
               s.views_count, s.delta_views, s.comments_count, s.delta_comments,
               s.reactions_json
               FROM reaction_snapshots s JOIN posts p ON p.id=s.post_id
               JOIN channels c ON c.id=p.channel_id ORDER BY c.username, p.id, s.measured_at"""
        )
        return csv_response(
            "snapshots.csv",
            ["канал", "id_публикации", "опубликовано", "измерено", "возраст_часов",
             "реакций_всего", "изменение_реакций", "просмотры", "изменение_просмотров",
             "комментарии", "изменение_комментариев", "реакции_json"],
            [list(row) for row in rows],
        )

    @app.get("/export/posts.csv")
    async def export_posts() -> StreamingResponse:
        rows = db.query(
            """SELECT c.username, p.telegram_message_id, p.published_at, p.history_complete,
               (SELECT total_reactions FROM reaction_snapshots s WHERE s.post_id=p.id ORDER BY measured_at DESC LIMIT 1),
               (SELECT views_count FROM reaction_snapshots s WHERE s.post_id=p.id ORDER BY measured_at DESC LIMIT 1),
               (SELECT comments_count FROM reaction_snapshots s WHERE s.post_id=p.id ORDER BY measured_at DESC LIMIT 1),
               (SELECT max(delta_total) FROM reaction_snapshots s WHERE s.post_id=p.id),
               (SELECT age_seconds/3600.0 FROM reaction_snapshots s WHERE s.post_id=p.id ORDER BY delta_total DESC LIMIT 1)
               FROM posts p JOIN channels c ON c.id=p.channel_id ORDER BY c.username, p.published_at"""
        )
        return csv_response(
            "posts.csv",
            ["канал", "id_публикации", "опубликовано", "полная_история",
             "последнее_число_реакций", "последнее_число_просмотров",
             "последнее_число_комментариев", "максимальный_скачок",
             "возраст_скачка_часов"],
            [list(row) for row in rows],
        )

    return app
