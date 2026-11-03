#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/inputs /task/truth
# A dim, blue-tinted living room at dusk: dark cool walls, a brown sofa, a pale window and a lamp shade.
convert -size 1800x1200 gradient:'rgb(48,54,72)'-'rgb(16,20,32)' \
  -fill 'rgb(78,62,52)' -draw 'rectangle 200,700 900,1100' \
  -fill 'rgb(96,104,128)' -draw 'rectangle 1100,220 1600,760' \
  -fill 'rgb(120,112,100)' -draw 'polygon 1000,520 1080,380 1160,520' \
  -quality 92 /task/inputs/living_room_dusk.jpg
cp /task/inputs/living_room_dusk.jpg /task/truth/original.jpg
