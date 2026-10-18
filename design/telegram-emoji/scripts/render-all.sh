#!/bin/bash
# Рендер набора кастомных эмодзи m-ranked в out/emoji/ по требованиям Telegram:
# WebM VP9 с альфа-каналом, 100×100, 3 с, 30 к/с, ≤ 256 КБ. Плашки рендерятся
# роликом 500×100 и режутся на 5 квадратов (scripts/slice.sh). Нужен ffmpeg.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=out/emoji; rm -rf "$OUT"; mkdir -p "$OUT/bands"
render() { npx remotion render "$1" "$2" --codec=vp9 --image-format=png --pixel-format=yuva420p --crf=30 --log=error; }
for id in logo spike anomaly alert-urgent telegram vk max rutube rank-1 rank-2 rank-3 up down promo; do
  render "$id" "$OUT/$id.webm"
done
for id in band-ours band-others band-week band-forecast band-posts band-server band-problems band-collection band-server2; do
  render "$id" "$OUT/bands/$id.webm"
done
bash scripts/slice.sh "$OUT/bands" "$OUT"
ls -la "$OUT"
