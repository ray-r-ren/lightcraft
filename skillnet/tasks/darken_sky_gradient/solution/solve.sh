#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/outputs
cp /task/inputs/meadow.jpg /tmp/meadow.jpg
cat > /tmp/s.jsonl <<'JSON'
{"command":"mask.add","params":{"kind":"linear","start":[0.5,0.0],"end":[0.5,0.45]}}
{"command":"mask.adjust","params":{"values":{"exposure":-1.0}}}
{"command":"app.export","params":{"path":"/task/outputs/meadow_sky.jpg","longEdge":0,"quality":92,"format":"jpeg"}}
JSON
lightcraft-cli run --import /tmp/meadow.jpg --script /tmp/s.jsonl
