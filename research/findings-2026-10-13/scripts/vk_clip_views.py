"""Есть ли у клипа ВК собственный счётчик просмотров: один read-only вызов wall.getById.

Запуск там, где задан токен сборщика ВК, например внутри его контейнера:

    python3 - < vk_clip_views.py

Токен читается из VK_ACCESS_TOKEN и нигде не печатается. Выводятся только
просмотры записи и числовые поля вложений video: просмотры видео, тип,
длительность. Только стандартная библиотека.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

POSTS = (
    "-55381799_115600",   # КБГУ, клип 24.09
    "-71938736_238136",   # Губкинский, клип 01.10
    "-69589815_35481",    # НИЯУ МИФИ, клип 12.09
)
VIDEO_FIELDS = ("type", "duration", "views", "local_views", "platform", "is_clip", "can_play")

token = os.environ.get("VK_ACCESS_TOKEN", "").strip()
if not token:
    sys.exit("VK_ACCESS_TOKEN не задан в этом окружении")
query = urllib.parse.urlencode({"posts": ",".join(POSTS), "v": "5.199", "access_token": token})
request = urllib.request.Request("https://api.vk.com/method/wall.getById", data=query.encode(), method="POST")
with urllib.request.urlopen(request, timeout=30) as response:
    payload = json.load(response)
if "error" in payload:
    error = payload["error"]
    sys.exit(f"VK error {error.get('error_code')}: {error.get('error_msg')}")
response = payload.get("response")
items = response.get("items", []) if isinstance(response, dict) else response or []
for post in items:
    videos = [{key: (item.get("video") or {}).get(key) for key in VIDEO_FIELDS}
              for item in post.get("attachments") or [] if item.get("type") == "video"]
    print(json.dumps({"post": f"{post.get('owner_id')}_{post.get('id')}",
                      "postViews": (post.get("views") or {}).get("count"),
                      "likes": (post.get("likes") or {}).get("count"),
                      "videos": videos}, ensure_ascii=False))
