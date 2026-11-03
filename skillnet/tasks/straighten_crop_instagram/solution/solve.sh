#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/outputs
cp /task/inputs/coast_tilted.jpg /tmp/coast.jpg
cat > /tmp/s.jsonl <<'JSON'
{"command":"crop.straighten","params":{"angle":-4}}
{"command":"crop.aspect","params":{"aspect":[4,5]}}
{"command":"app.export","params":{"path":"/task/outputs/coast_4x5.jpg","longEdge":0,"quality":92,"format":"jpeg"}}
JSON
lightcraft-cli run --import /tmp/coast.jpg --script /tmp/s.jsonl
