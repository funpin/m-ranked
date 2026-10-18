#!/bin/bash
# Режет плашки 500×100 на пять квадратов 100×100: <имя>-1.webm … <имя>-5.webm,
# с сохранением прозрачности (декодер libvpx-vp9 читает альфа-канал).
set -euo pipefail
src=$1; dst=$2
for banner in "$src"/*.webm; do
  stem=$(basename "$banner" .webm)
  for i in 1 2 3 4 5; do
    ffmpeg -v error -y -c:v libvpx-vp9 -i "$banner" -vf "crop=100:100:$(( (i - 1) * 100 )):0" \
      -c:v libvpx-vp9 -pix_fmt yuva420p -crf 30 -b:v 0 -an -r 30 "$dst/$stem-$i.webm"
  done
  echo "$stem → 5 tiles"
done
