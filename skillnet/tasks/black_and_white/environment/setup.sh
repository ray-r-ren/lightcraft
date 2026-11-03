#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/inputs /task/truth
convert -size 2000x1333 gradient:'rgb(240,140,60)'-'rgb(40,60,140)' \
  -fill 'rgb(220,40,50)' -draw 'circle 600,700 600,900' \
  -fill 'rgb(40,200,90)' -draw 'rectangle 1200,500 1600,1100' \
  -quality 92 /task/inputs/street_colour.jpg
cp /task/inputs/street_colour.jpg /task/truth/original.jpg
