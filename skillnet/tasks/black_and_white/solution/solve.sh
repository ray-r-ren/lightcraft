#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/outputs
lightcraft-cli render /task/inputs/street_colour.jpg -o /task/outputs/street_bw.jpg --preset lc.bw-high-contrast
