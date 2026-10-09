"""Прокси Telegram custom emoji для совместимости старых страниц."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from ..emoji_proxy import CACHE, EmojiMissing, EmojiUpstream
from ..errors import ApiProblem

router = APIRouter(tags=["Media"])


@router.get("/api/v1/emoji/{emojiId}")
async def custom_emoji(emojiId: str) -> Response:
    if not emojiId.isascii() or not emojiId.isdigit() or not 1 <= len(emojiId) <= 32:
        raise ApiProblem(404, "Resource not found", "Реакция не найдена",
                         "urn:m-ranked:problem:not-found")
    try:
        asset = await CACHE.get(emojiId)
    except EmojiMissing as error:
        raise ApiProblem(404, "Resource not found", "Реакция не найдена",
                         "urn:m-ranked:problem:not-found") from error
    except EmojiUpstream as error:
        # Источник недоступен — для страницы это та же «нет картинки»: она
        # покажет свой значок. 404 с коротким кэшем вместо 500 через 10 с.
        raise ApiProblem(404, "Resource not found", "Реакция временно недоступна",
                         "urn:m-ranked:problem:not-found",
                         headers={"Cache-Control": "public, max-age=600"}) from error
    # Картинка custom emoji по номеру не меняется: месяц и immutable — повторы
    # отдаёт кэш nginx и браузера, а не холодный запрос в Telegram (до 10 с).
    return Response(asset.content, media_type=asset.media_type,
                    headers={"Cache-Control": "public, max-age=2592000, immutable"})
