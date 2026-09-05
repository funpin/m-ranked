from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import re
import stat

from app.config import Settings

from .model import Platform


MAX_AUTH_FILE_BYTES = 16 * 1024
_KEY = re.compile(r"[A-Z][A-Z0-9_]*")
_ALLOWED_KEYS = {
    Platform.TELEGRAM: frozenset({"TELEGRAM_API_ID", "TELEGRAM_API_HASH"}),
    Platform.VK: frozenset({"VK_ACCESS_TOKEN"}),
    Platform.MAX: frozenset({"MAX_USER_PHONE"}),
    Platform.RUTUBE: frozenset(),
}


class PlatformAuthFileError(RuntimeError):
    """Safe classification for a credential file rejected before startup."""


def _reject(reason: str) -> PlatformAuthFileError:
    # Reasons are fixed classifications and never interpolate paths or values.
    return PlatformAuthFileError(reason)


def _has_trusted_permissions(metadata: os.stat_result) -> bool:
    return (
        stat.S_IMODE(metadata.st_mode) in {0o400, 0o600}
        and metadata.st_uid in {0, os.geteuid()}
    )


def _read_secure_file(path: str | Path) -> str:
    value = os.fspath(path)
    if not value or "\x00" in value:
        raise _reject("invalid credential path")
    try:
        metadata = os.lstat(value)
    except OSError as error:
        raise _reject("credential file is not readable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise _reject("credential path is not a regular file")
    if not _has_trusted_permissions(metadata):
        raise _reject("credential file permissions are too broad")
    if metadata.st_size > MAX_AUTH_FILE_BYTES:
        raise _reject("credential file is too large")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(value, flags)
    except OSError as error:
        raise _reject("credential file open failed") from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            or not _has_trusted_permissions(opened)
            or opened.st_size > MAX_AUTH_FILE_BYTES
        ):
            raise _reject("credential file changed during validation")
        chunks: list[bytes] = []
        remaining = MAX_AUTH_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
    except OSError as error:
        raise _reject("credential file read failed") from error
    finally:
        os.close(descriptor)
    if len(payload) > MAX_AUTH_FILE_BYTES:
        raise _reject("credential file is too large")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _reject("credential file is not UTF-8") from error


def parse_platform_auth_file(
    platform: Platform,
    path: str | Path,
) -> dict[str, str]:
    allowed = _ALLOWED_KEYS[platform]
    result: dict[str, str] = {}
    for raw_line in _read_secure_file(path).splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        key, separator, raw_value = raw_line.partition("=")
        if (
            not separator
            or not _KEY.fullmatch(key)
            or key not in allowed
            or key in result
            or not raw_value
            or raw_value != raw_value.strip()
            or "\x00" in raw_value
        ):
            raise _reject("credential file contains an invalid entry")
        result[key] = raw_value
    return result


def apply_platform_auth_file(
    settings: Settings,
    platform: Platform,
    path: str | Path | None,
) -> Settings:
    """Return settings populated from one platform-scoped credential bundle."""
    if path is None or not os.fspath(path).strip():
        return settings
    values = parse_platform_auth_file(platform, path)
    expected = _ALLOWED_KEYS[platform]
    if platform == Platform.TELEGRAM and settings.data_source != "mtproto":
        expected = frozenset()
    if frozenset(values) != expected:
        raise _reject("credential file keys are incomplete for platform mode")

    direct_values = {
        "TELEGRAM_API_ID": settings.telegram_api_id,
        "TELEGRAM_API_HASH": settings.telegram_api_hash,
        "VK_ACCESS_TOKEN": settings.vk_access_token,
        "MAX_USER_PHONE": settings.max_user_phone,
    }
    if any(direct_values[key] is not None for key in _ALLOWED_KEYS[platform]):
        raise _reject("direct and file credentials cannot be combined")

    if platform == Platform.TELEGRAM:
        if not values:
            return settings
        try:
            api_id = int(values["TELEGRAM_API_ID"])
        except (TypeError, ValueError) as error:
            raise _reject("telegram API id is invalid") from error
        if api_id <= 0:
            raise _reject("telegram API id is invalid")
        return replace(
            settings,
            telegram_api_id=api_id,
            telegram_api_hash=values["TELEGRAM_API_HASH"],
        )
    if platform == Platform.VK:
        return replace(settings, vk_access_token=values["VK_ACCESS_TOKEN"])
    if platform == Platform.MAX:
        return replace(settings, max_user_phone=values["MAX_USER_PHONE"])
    return settings
