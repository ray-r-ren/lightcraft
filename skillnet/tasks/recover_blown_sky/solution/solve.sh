#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/outputs
lightcraft-cli render /task/inputs/lake_overexposed.jpg -o /task/outputs/lake_recovered.jpg \
  --set light.highlights=-80 --set light.whites=-30
