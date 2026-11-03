#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/inputs /task/truth
convert -size 2400x1600 gradient:'rgb(150,185,220)'-'rgb(70,95,60)' -quality 90 /task/inputs/field_01.jpg
convert -size 2400x1600 gradient:'rgb(200,205,210)'-'rgb(60,62,70)' -quality 90 /task/inputs/street_02.jpg
convert -size 1600x2400 gradient:'rgb(170,190,210)'-'rgb(90,80,70)' -quality 90 /task/inputs/tower_03.jpg
convert -size 2400x1600 radial-gradient:'rgb(210,210,200)'-'rgb(40,50,60)' -quality 90 /task/inputs/lamp_04.jpg
cp /task/inputs/*.jpg /task/truth/
