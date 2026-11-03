#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/inputs /task/truth
convert -size 2400x700 gradient:'rgb(170,200,235)'-'rgb(215,228,242)' \
  \( -size 2400x900 gradient:'rgb(110,140,80)'-'rgb(50,75,40)' \) -append \
  -quality 92 /task/inputs/meadow.jpg
cp /task/inputs/meadow.jpg /task/truth/original.jpg
