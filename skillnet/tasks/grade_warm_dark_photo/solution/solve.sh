#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/outputs
# Brighten with a gamma lift and warm by raising red / lowering blue, with ImageMagick alone.
convert /task/inputs/living_room_dusk.jpg -level 0%,70%,1.6 \
  -channel R -evaluate multiply 1.15 -channel B -evaluate multiply 0.85 +channel \
  -quality 92 /task/outputs/living_room_warm.jpg
