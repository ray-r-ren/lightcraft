#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/inputs /task/truth
cd /task/inputs
# overexposed: big pure-white sky, bright pale water
convert -size 2000x700 xc:white \( -size 2000x633 gradient:'rgb(235,240,250)'-'rgb(190,205,220)' \) -append -quality 92 harbour.jpg
# underexposed: very dark greens
convert -size 2000x1333 gradient:'rgb(40,52,35)'-'rgb(8,14,6)' -quality 92 forest.jpg
# well exposed: mid-tone colourful blocks
convert -size 2000x1333 gradient:'rgb(170,140,110)'-'rgb(70,90,120)' \
  -fill 'rgb(200,60,50)' -draw 'rectangle 200,600 700,1100' \
  -fill 'rgb(60,140,80)' -draw 'rectangle 900,500 1400,1100' -quality 92 market.jpg
for f in harbour forest market; do
  case $f in harbour) iso=200;; forest) iso=3200;; market) iso=400;; esac
  exiftool -q -overwrite_original -Make=FUJIFILM -Model=X-T4 -LensModel='XF16-80mmF4 R OIS WR' \
    -ISO=$iso -ExposureTime=1/250 -FNumber=5.6 -DateTimeOriginal='2023:06:14 17:42:10' $f.jpg
done
printf 'harbour.jpg: overexposed\nforest.jpg: underexposed\nmarket.jpg: fine\ncamera: X-T4\nforest ISO: 3200\n' > /task/truth/answer.txt
