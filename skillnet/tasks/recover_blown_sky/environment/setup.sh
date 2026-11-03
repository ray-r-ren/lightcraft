#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/inputs /task/truth
convert -size 2400x420 xc:white \
  \( -size 2400x480 gradient:white-'rgb(200,220,245)' \) \
  \( -size 2400x1100 gradient:'rgb(120,160,90)'-'rgb(40,70,30)' \) \
  -append -quality 92 /task/inputs/lake_overexposed.jpg
cp /task/inputs/lake_overexposed.jpg /task/truth/original.jpg
