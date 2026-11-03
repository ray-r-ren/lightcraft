#!/bin/bash
set -e
set -euo pipefail
cd /task/inputs
out=""
for f in harbour.jpg forest.jpg market.jpg; do
  m=$(convert "$f" -colorspace Gray -format '%[fx:mean]' info:)
  hi=$(convert "$f" -colorspace Gray -threshold 98% -format '%[fx:mean]' info:)
  v=$(python3 -c "m=$m; h=$hi; print('overexposed' if h > 0.05 or m > 0.75 else 'underexposed' if m < 0.2 else 'fine')")
  out+="$f: $v"$'\n'
done
model=$(exiftool -s3 -Model forest.jpg)
iso=$(exiftool -s3 -ISO forest.jpg)
printf '%scamera: %s\nforest ISO: %s\n' "$out" "$model" "$iso" > /task/answer.txt
cat /task/answer.txt
