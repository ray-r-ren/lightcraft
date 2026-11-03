#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/inputs /task/truth
convert -size 3000x1000 gradient:'rgb(120,170,225)'-'rgb(200,220,240)' \
  \( -size 3000x1000 gradient:'rgb(95,130,70)'-'rgb(45,70,35)' \) -append \
  -background 'rgb(45,70,35)' -rotate 4 -gravity center -crop 2400x1600+0+0 +repage \
  -quality 92 /task/inputs/coast_tilted.jpg
echo 4 > /task/truth/tilt_degrees.txt
